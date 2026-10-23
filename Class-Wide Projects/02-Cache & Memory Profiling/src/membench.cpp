// Linux / WSL2 x86-64 memory hierarchy benchmark. See docs in README.md.
// Volatile accesses are deliberate: explicit scalar useful-byte accounting.
#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <linux/perf_event.h>
#ifndef MAP_HUGE_2MB
#define MAP_HUGE_2MB (21 << 26)
#endif
#include <map>
#include <numeric>
#include <random>
#include <sched.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <thread>
#include <unistd.h>
#include <vector>
using u64=uint64_t;
static constexpr size_t HP=2*1024*1024;
static u64 sink=0;
static u64 now_ns(){ timespec t{}; if(clock_gettime(CLOCK_MONOTONIC_RAW,&t)) throw std::runtime_error("clock_gettime"); return u64(t.tv_sec)*1000000000+t.tv_nsec; }
static std::string esc(const std::string&s){std::ostringstream o;o<<'"';for(unsigned char c:s){if(c=='"'||c=='\\')o<<'\\'<<c;else if(c=='\n')o<<"\\n";else if(c<32)o<<' ';else o<<c;}o<<'"';return o.str();}
struct Json {
 std::map<std::string,std::string> v;
 void str(const std::string&k,const std::string&s){v[k]=esc(s);}
 template<class T>void num(const std::string&k,T x){std::ostringstream o;o<<std::setprecision(15)<<x;v[k]=o.str();}
 void print(){std::cout<<"{";bool f=true;for(auto&x:v){if(!f)std::cout<<",";f=false;std::cout<<esc(x.first)<<":"<<x.second;}std::cout<<"}\n";}
};
struct Args {
 std::map<std::string,std::string> a;
 Args(int argc,char**argv){for(int i=1;i<argc;i+=2){if(i+1>=argc||std::string(argv[i]).substr(0,2)!="--")throw std::runtime_error("use --key value pairs");a[std::string(argv[i]).substr(2)]=argv[i+1];}}
 std::string s(std::string k,std::string d="")const{auto p=a.find(k);return p==a.end()?d:p->second;}
 u64 n(std::string k,u64 d)const{auto x=s(k);if(x.empty())return d;if(x[0]=='-')throw std::runtime_error("negative "+k);size_t end=0;u64 v=std::stoull(x,&end);if(end!=x.size())throw std::runtime_error("invalid "+k);return v;}
};
static void pin(int cpu){if(cpu<0||cpu>=CPU_SETSIZE)throw std::runtime_error("invalid cpu");cpu_set_t s;CPU_ZERO(&s);CPU_SET(cpu,&s);if(sched_setaffinity(0,sizeof(s),&s))throw std::runtime_error(std::string("affinity: ")+strerror(errno));}
struct Mapping {
 char*p=nullptr;size_t bytes=0;std::string mode;int advice_errno=0;
 Mapping(size_t requested,const std::string&m):mode(m){
  if(!requested||requested>size_t(16)*1024*1024*1024)throw std::runtime_error("mapping size out of range");
  if(m!="base"&&m!="thp"&&m!="hugetlb")throw std::runtime_error("invalid pages mode");
  size_t align=m=="base"?size_t(sysconf(_SC_PAGESIZE)):HP;bytes=(requested+align-1)/align*align;
  if(m=="hugetlb"){
   void*q=mmap(nullptr,bytes,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_HUGETLB|MAP_HUGE_2MB,-1,0);
   if(q==MAP_FAILED)throw std::runtime_error(std::string("hugetlb unavailable: ")+strerror(errno));
   p=(char*)q;
  }else{
   void*q=mmap(nullptr,bytes+HP,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
   if(q==MAP_FAILED)throw std::runtime_error(std::string("mmap: ")+strerror(errno));
   uintptr_t b=(uintptr_t(q)+HP-1)&~uintptr_t(HP-1);size_t pre=b-uintptr_t(q),post=HP-pre;
   if(pre)munmap(q,pre);
   if(post)munmap((void*)(b+bytes),post);
   p=(char*)b;
   if(madvise(p,bytes,m=="base"?MADV_NOHUGEPAGE:MADV_HUGEPAGE)){
    advice_errno=errno;if(m=="base")throw std::runtime_error("MADV_NOHUGEPAGE failed; base pages cannot be controlled");
   }
  }
  // First touch is on the already pinned allocating thread, outside timing.
  memset(p,1,bytes);
 }
 Mapping(const Mapping&)=delete;Mapping&operator=(const Mapping&)=delete;
 ~Mapping(){if(p)munmap(p,bytes);}
 void info(Json&j)const{
  j.num("mapped_bytes",bytes);j.num("page_advice_errno",advice_errno);
  std::ifstream f("/proc/self/smaps");std::string l;bool active=false;u64 ah=0,kp=0,mp=0;bool seen=false;
  while(std::getline(f,l)){
   unsigned long long b,e;if(sscanf(l.c_str(),"%llx-%llx",&b,&e)==2)active=(uintptr_t(p)>=b&&uintptr_t(p)<e);
   if(active){seen=true;u64 x=0;if(sscanf(l.c_str(),"AnonHugePages: %lu kB",&x)==1)ah=x;
    if(sscanf(l.c_str(),"KernelPageSize: %lu kB",&x)==1)kp=x;
    if(sscanf(l.c_str(),"MMUPageSize: %lu kB",&x)==1)mp=x;}
  }
  if(seen){j.num("anon_huge_kib",ah);j.num("kernel_page_kib",kp);j.num("mmu_page_kib",mp);}
  j.str("page_status",mode=="hugetlb"?"explicit_2MiB":!seen?"unverified":mode=="thp"?(ah*1024>=bytes?"thp_full":ah?"thp_partial":"thp_not_observed"):"nohuge_advice");
 }
};
struct Event {std::string name;int fd=-1,err=0;};
struct Counters {
 std::vector<Event> ev;
 Counters(bool enabled){if(!enabled)return;
  add("cycles",PERF_TYPE_HARDWARE,PERF_COUNT_HW_CPU_CYCLES);
  add("instructions",PERF_TYPE_HARDWARE,PERF_COUNT_HW_INSTRUCTIONS);
  add("cache_references",PERF_TYPE_HARDWARE,PERF_COUNT_HW_CACHE_REFERENCES);
  add("cache_misses",PERF_TYPE_HARDWARE,PERF_COUNT_HW_CACHE_MISSES);
  add("l1d_read_misses",PERF_TYPE_HW_CACHE,PERF_COUNT_HW_CACHE_L1D|(PERF_COUNT_HW_CACHE_OP_READ<<8)|(PERF_COUNT_HW_CACHE_RESULT_MISS<<16));
  add("dtlb_read_misses",PERF_TYPE_HW_CACHE,PERF_COUNT_HW_CACHE_DTLB|(PERF_COUNT_HW_CACHE_OP_READ<<8)|(PERF_COUNT_HW_CACHE_RESULT_MISS<<16));
 }
 void add(std::string n,u64 type,u64 config){perf_event_attr a{};a.size=sizeof(a);a.type=type;a.config=config;a.disabled=1;a.exclude_kernel=1;a.exclude_hv=1;a.read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING;
  int fd=syscall(__NR_perf_event_open,&a,0,-1,-1,PERF_FLAG_FD_CLOEXEC);ev.push_back({n,fd,fd<0?errno:0});}
 void start(){for(auto&e:ev)if(e.fd>=0){if(ioctl(e.fd,PERF_EVENT_IOC_RESET,0)||ioctl(e.fd,PERF_EVENT_IOC_ENABLE,0))e.err=errno;}}
 void stop(Json&j){for(auto&e:ev){if(e.fd<0||e.err){j.str(e.name+"_status",strerror(e.err));continue;}if(ioctl(e.fd,PERF_EVENT_IOC_DISABLE,0)){j.str(e.name+"_status",strerror(errno));continue;}
  struct {u64 value,enabled,running;}v{};if(read(e.fd,&v,sizeof(v))!=sizeof(v)||!v.running){j.str(e.name+"_status","not_running");continue;}
  j.num(e.name+"_raw",v.value);j.num(e.name+"_enabled_ns",v.enabled);j.num(e.name+"_running_ns",v.running);
  j.num(e.name+"_running_fraction",double(v.running)/v.enabled);j.num(e.name+"_scaled",double(v.value)*v.enabled/v.running);j.str(e.name+"_status","ok");
 }}
 ~Counters(){for(auto&e:ev)if(e.fd>=0)close(e.fd);}
};
static std::vector<size_t> offsets(size_t bytes,size_t stride,const std::string&pattern,u64 seed,size_t nodes=0,const std::string&locality="regular"){
 if(stride<8||stride%8)throw std::runtime_error("stride must be an aligned multiple of 8");
 size_t n=nodes?nodes:bytes/stride;if(n<2)throw std::runtime_error("at least two nodes required");std::vector<size_t>v(n);
 for(size_t i=0;i<n;i++)v[i]=locality=="spread"?i*4096+((i*64)%4096):locality=="compact"?i*64:i*stride;
 if(*std::max_element(v.begin(),v.end())+8>bytes)throw std::runtime_error("nodes exceed mapping");
 if(pattern=="random"){std::mt19937_64 r(seed);std::shuffle(v.begin(),v.end(),r);}else if(pattern!="sequential")throw std::runtime_error("invalid pattern");return v;
}
// One cycle through every node, with no index array in the timed chase.
static uintptr_t make_ring(Mapping&m,const std::vector<size_t>&v){for(size_t i=0;i<v.size();i++)*reinterpret_cast<uintptr_t*>(m.p+v[i])=reinterpret_cast<uintptr_t>(m.p+v[(i+1)%v.size()]);return reinterpret_cast<uintptr_t>(m.p+v[0]);}
static inline uintptr_t chase(uintptr_t p,u64 n){for(u64 i=0;i<n;i++)p=*reinterpret_cast<volatile uintptr_t*>(p);return p;}
struct Sample {u64 ns=0,ops=0,bytes=0,checksum=0;};
template<class F>static Sample timed(F f,u64 target){Sample s;u64 t=now_ns();do{auto a=f();s.ops+=a.ops;s.bytes+=a.bytes;s.checksum^=a.checksum;}while(now_ns()-t<target);s.ns=now_ns()-t;return s;}
static void metrics(Json&j,const Sample&s){j.num("elapsed_ns",s.ns);j.num("operations",s.ops);j.num("useful_bytes",s.bytes);j.num("useful_gbps",double(s.bytes)/s.ns);j.num("ns_per_operation",double(s.ns)/s.ops);j.num("checksum",s.checksum);sink^=s.checksum;}
static Sample stream_batch(Mapping&m,const std::vector<size_t>&order,size_t gran,int readpct,u64 pass){
 u64 sum=0;for(size_t k=0;k<order.size();k++){
  bool rd=int(k%10)<readpct/10;volatile u64*p=reinterpret_cast<volatile u64*>(m.p+order[k]);
  for(size_t w=0;w<gran/8;w++){if(rd)sum+=p[w];else p[w]=pass+k+w;}
 }
 // Ensures all temporal stores have passed the store buffer before batch ends.
 asm volatile("mfence" ::: "memory");return {0,order.size(),order.size()*gran,sum};
}
static void run_chase(const Args&a,Json&j){
 size_t bytes=a.n("bytes",64*1024*1024),stride=a.n("stride",64),n=a.n("nodes",0);std::string loc=a.s("locality","regular");
 Mapping m(bytes,a.s("pages","base"));auto v=offsets(bytes,stride,a.s("pattern","random"),a.n("seed",1),n,loc);uintptr_t p=make_ring(m,v);
 p=chase(p,v.size());m.info(j);j.num("nodes",v.size());j.num("line_footprint_bytes",v.size()*64);
 Counters c(a.n("counters",1));rusage before{},after{};getrusage(RUSAGE_THREAD,&before);c.start();
 Sample s=timed([&]{p=chase(p,4096);return Sample{0,4096,4096*8,u64(p)};},a.n("ms",200)*1000000);getrusage(RUSAGE_THREAD,&after);c.stop(j);metrics(j,s);j.num("latency_ns",double(s.ns)/s.ops);j.num("minor_faults",after.ru_minflt-before.ru_minflt);j.num("major_faults",after.ru_majflt-before.ru_majflt);j.num("involuntary_switches",after.ru_nivcsw-before.ru_nivcsw);
}
static void run_stream(const Args&a,Json&j){
 size_t bytes=a.n("bytes",64*1024*1024),stride=a.n("stride",64),gran=a.n("granularity",64);int r=a.n("read_pct",100);
 if((gran!=8&&gran!=64)||gran>stride||(r!=0&&r!=50&&r!=70&&r!=100))throw std::runtime_error("invalid granularity or mix");
 Mapping m(bytes,a.s("pages","base"));auto order=offsets(bytes,stride,a.s("pattern","sequential"),a.n("seed",1));
 size_t reads=0;for(size_t k=0;k<order.size();k++)reads+=int(k%10)<r/10;j.num("actual_read_fraction",double(reads)/order.size());j.num("nodes",order.size());j.num("line_footprint_bytes",order.size()*64);j.num("index_bytes",order.size()*sizeof(size_t));
 sink^=stream_batch(m,order,gran,r,0).checksum;m.info(j);u64 pass=1;Counters c(a.n("counters",1));c.start();auto s=timed([&]{return stream_batch(m,order,gran,r,pass++);},a.n("ms",200)*1000000);c.stop(j);metrics(j,s);
 // ns_per_operation is reciprocal throughput, not dependent-load latency.
}
static Sample kernel_batch(Mapping&m,size_t elements,const std::vector<size_t>&v,bool axpy){
 volatile double*x=reinterpret_cast<volatile double*>(m.p),*y=x+elements,*z=y+elements;double check=0;
 for(size_t i:v){if(axpy)y[i]=0.5*x[i]+y[i];else z[i]=x[i]*y[i];}
 asm volatile("mfence" ::: "memory");check=axpy?y[v.back()]:z[v.back()];u64 bits;memcpy(&bits,&check,8);return {0,v.size(),v.size()*24,bits};
}
static void run_kernel(const Args&a,Json&j){
 size_t bytes=a.n("bytes",64*1024*1024),elems=bytes/24,step=a.n("element_stride",1);if(elems<2||!step)throw std::runtime_error("invalid kernel size");
 Mapping m(elems*24,a.s("pages","base"));double*x=reinterpret_cast<double*>(m.p);for(size_t i=0;i<elems*3;i++)x[i]=1.0;
 std::vector<size_t>v;for(size_t i=0;i<elems;i+=step)v.push_back(i);if(a.s("pattern","sequential")=="random"){std::mt19937_64 r(a.n("seed",1));std::shuffle(v.begin(),v.end(),r);}
 bool axpy=a.s("kernel","multiply")=="axpy";sink^=kernel_batch(m,elems,v,axpy).checksum;m.info(j);j.num("elements_per_array",elems);j.num("index_bytes",v.size()*8);Counters c(a.n("counters",1));c.start();auto s=timed([&]{return kernel_batch(m,elems,v,axpy);},a.n("ms",200)*1000000);c.stop(j);metrics(j,s);
}
static std::vector<int> cpulist(const std::string&s){std::vector<int>v;std::istringstream in(s);std::string x;while(std::getline(in,x,','))v.push_back(std::stoi(x));return v;}
static void run_loaded(const Args&a,Json&j){
 auto cpus=cpulist(a.s("load_cpus"));size_t bytes=a.n("bytes",64*1024*1024),probe_bytes=a.n("probe_bytes",bytes);int r=a.n("read_pct",100);if(r!=0&&r!=50&&r!=70&&r!=100)throw std::runtime_error("invalid mix");
 Mapping probe(probe_bytes,"base");auto v=offsets(probe_bytes,64,"random",a.n("seed",1));uintptr_t p=make_ring(probe,v);p=chase(p,v.size());probe.info(j);
 std::atomic<int>ready{0};std::atomic<bool>go{false},stop{false};std::vector<Sample>stats(cpus.size());std::vector<std::string>errors(cpus.size());std::vector<std::thread>threads;
 for(size_t t=0;t<cpus.size();t++)threads.emplace_back([&,t]{try{
  pin(cpus[t]);Mapping m(bytes,"base");auto ord=offsets(bytes,64,a.s("pattern","sequential"),a.n("seed",1)+t); // Worker state is private.
  auto warm=stream_batch(m,ord,64,r,0);stats[t].checksum=warm.checksum;ready.fetch_add(1);while(!go.load(std::memory_order_acquire))std::this_thread::yield();u64 start=now_ns(),pass=1;
  do{auto s=stream_batch(m,ord,64,r,pass++);stats[t].ops+=s.ops;stats[t].bytes+=s.bytes;stats[t].checksum^=s.checksum;}while(!stop.load(std::memory_order_relaxed));stats[t].ns=now_ns()-start;
 }catch(const std::exception&e){errors[t]=e.what();ready.fetch_add(1);}});
 while(ready.load()!=int(cpus.size()))std::this_thread::yield();
 bool bad=false;for(auto&e:errors)bad|=!e.empty();
 u64 t0=now_ns();go.store(true,std::memory_order_release);u64 ops=0;while(!bad&&now_ns()-t0<a.n("ms",200)*1000000){p=chase(p,4096);ops+=4096;}u64 t1=now_ns();stop.store(true);for(auto&t:threads)t.join();
 for(auto&e:errors)if(!e.empty())throw std::runtime_error(e);
 u64 total=0,maxend=t1-t0;double rates=0;for(auto&s:stats){total+=s.bytes;maxend=std::max(maxend,s.ns);rates+=double(s.bytes)/s.ns;sink^=s.checksum;}
 j.num("load_threads",cpus.size());j.num("probe_operations",ops);j.num("latency_ns",double(t1-t0)/ops);j.num("elapsed_ns",t1-t0);j.num("load_useful_bytes",total);j.num("load_useful_gbps",rates);j.num("load_tail_ns",maxend-(t1-t0));j.num("checksum",u64(p));j.str("counters_status","not_collected_for_concurrent_sweep");
}
static void selftest(){
 pin(sched_getcpu());for(auto pat:{"sequential","random"}){Mapping m(65536,"base");auto v=offsets(65536,64,pat,23);auto p=make_ring(m,v),q=p;std::vector<uintptr_t>seen;for(size_t i=0;i<v.size();i++){seen.push_back(q);q=chase(q,1);}std::sort(seen.begin(),seen.end());if(q!=p||std::adjacent_find(seen.begin(),seen.end())!=seen.end())throw std::runtime_error("ring verification failed");}
 Mapping m(4096,"base");auto v=offsets(4096,64,"sequential",1);for(int r:{0,50,70,100}){stream_batch(m,v,64,r,13);for(size_t k=0;k<v.size();k++)if(int(k%10)>=r/10)for(size_t w=0;w<8;w++)if(reinterpret_cast<u64*>(m.p+v[k])[w]!=13+k+w)throw std::runtime_error("store verification failed");}
 Mapping k(24*128,"base");double*x=reinterpret_cast<double*>(k.p);for(int i=0;i<128;i++){x[i]=2;x[128+i]=3;}std::vector<size_t>ix(128);std::iota(ix.begin(),ix.end(),0);kernel_batch(k,128,ix,false);for(int i=0;i<128;i++)if(x[256+i]!=6)throw std::runtime_error("multiply verification failed");kernel_batch(k,128,ix,true);for(int i=0;i<128;i++)if(x[128+i]!=4)throw std::runtime_error("axpy verification failed");
}
int main(int argc,char**argv){Json j;try{Args a(argc,argv);std::string mode=a.s("mode","chase");if(mode=="selftest"){selftest();j.str("status","ok");j.str("test","ring_stream_kernels");j.print();return 0;}
 pin(int(a.n("cpu",sched_getcpu())));j.num("cpu_start",sched_getcpu());u64 overhead=~u64(0);for(int i=0;i<100;i++){u64 t=now_ns();overhead=std::min(overhead,now_ns()-t);}j.num("clock_pair_min_ns",overhead);
 if(mode=="chase")run_chase(a,j);else if(mode=="stream")run_stream(a,j);else if(mode=="kernel")run_kernel(a,j);else if(mode=="loaded")run_loaded(a,j);else throw std::runtime_error("invalid mode");j.num("cpu_end",sched_getcpu());j.str("status","ok");j.print();return 0;
 }catch(const std::exception&e){j.str("status","error");j.str("error",e.what());j.print();return 2;}}
