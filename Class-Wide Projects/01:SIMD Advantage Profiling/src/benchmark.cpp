#include "kernels.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>
#include <x86intrin.h>
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#ifndef BUILD_VARIANT
#define BUILD_VARIANT "unknown"
#endif
volatile double sink=0;
struct Options {
    std::string kernel="saxpy", dtype="f32", pattern="positive";
    std::size_t n=1024, stride=1, shift=0;
    int samples=7;
    double seconds=0.1;
    bool validate_only=false;
};
std::size_t number(const std::string& s) {
    if(s.empty() || s[0]=='-') throw std::runtime_error("expected a nonnegative integer");
    std::size_t used=0; auto v=std::stoull(s,&used);
    if(used!=s.size() || v>std::numeric_limits<std::size_t>::max()) throw std::runtime_error("invalid integer");
    return static_cast<std::size_t>(v);
}
Options parse(int argc,char** argv) {
    Options o;
    for(int i=1;i<argc;++i) {
        std::string a=argv[i];
        if(a=="--validate-only") {o.validate_only=true; continue;}
        if(i+1==argc) throw std::runtime_error("missing option value");
        std::string v=argv[++i];
        if(a=="--kernel") o.kernel=v;
        else if(a=="--dtype") o.dtype=v;
        else if(a=="--n") o.n=number(v);
        else if(a=="--stride") o.stride=number(v);
        else if(a=="--shift") o.shift=number(v);
        else if(a=="--samples") {auto t=number(v); if(t>1000) throw std::runtime_error("too many samples"); o.samples=int(t);}
        else if(a=="--seconds") {std::size_t used=0;o.seconds=std::stod(v,&used);if(used!=v.size())throw std::runtime_error("invalid seconds");}
        else if(a=="--pattern") o.pattern=v;
        else throw std::runtime_error("unknown option: "+a);
    }
    if(o.n==0 || o.n>(1ull<<29) || o.shift>63 || o.samples<1 ||
       !std::isfinite(o.seconds) || o.seconds<=0 || o.seconds>10 ||
       (o.stride!=1 && o.stride!=2 && o.stride!=4 && o.stride!=8) ||
       (o.dtype!="f32" && o.dtype!="f64") ||
       (o.pattern!="positive" && o.pattern!="alternating")) throw std::runtime_error("invalid option range");
    return o;
}
struct Cycles {
    int fd=-1;
    Cycles() {
        perf_event_attr a{}; a.type=PERF_TYPE_HARDWARE; a.size=sizeof(a);
        a.config=PERF_COUNT_HW_CPU_CYCLES; a.disabled=1; a.exclude_kernel=1; a.exclude_hv=1;
        // Scale only if the event actually ran; preserve enabled/running times.
        a.read_format=PERF_FORMAT_TOTAL_TIME_ENABLED|PERF_FORMAT_TOTAL_TIME_RUNNING;
        fd=int(syscall(__NR_perf_event_open,&a,0,-1,-1,0));
    }
    ~Cycles(){if(fd>=0)close(fd);}
    void start(){if(fd>=0){ioctl(fd,PERF_EVENT_IOC_RESET,0);ioctl(fd,PERF_EVENT_IOC_ENABLE,0);}}
    double stop(){
        if(fd<0)return -1;
        ioctl(fd,PERF_EVENT_IOC_DISABLE,0);
        struct {std::uint64_t value,enabled,running;} data{};
        if(read(fd,&data,sizeof(data))!=sizeof(data) || data.running==0)return -1;
        return double(data.value)*double(data.enabled)/double(data.running);
    }
};
std::uint64_t tsc() {unsigned aux;_mm_lfence();auto v=__rdtscp(&aux);_mm_lfence();return v;}
template<class T> struct Buffer {
    T* base=nullptr; T* p=nullptr; std::size_t count,shift;
    Buffer(std::size_t size,std::size_t offset):count(size+offset+32),shift(offset) {
        if(posix_memalign(reinterpret_cast<void**>(&base),64,count*sizeof(T))!=0)throw std::bad_alloc();
        p=base+offset;
        std::fill(base,base+count,T(-12345));
    }
    ~Buffer(){std::free(base);}
    Buffer(const Buffer&)=delete;
    Buffer& operator=(const Buffer&)=delete;
};
template<class T> T input(std::size_t i,bool second,const std::string& pattern) {
    // Deterministic exactly representable normal finite values; no random library dependence.
    T v=second ? T(0.5)+T((i*29+3)%127)/T(256) : T(0.25)+T((i*17+11)%251)/T(512);
    if(pattern=="alternating" && second && (i&1))v=-v;
    return v;
}
template<class T> int run(const Options& o,int kind) {
    const std::size_t span=(o.n+1)*o.stride+1;
    // Bound per-case allocation rather than exhausting a laptop/WSL VM.
    if(span*sizeof(T)>512ull*1024*1024)throw std::runtime_error("allocation exceeds 512 MiB per array");
    Buffer<T> x(span,o.shift),y(span,o.shift),z(span,o.shift);
    auto reset=[&](){
        std::fill(x.base,x.base+x.count,T(-12345));
        std::fill(y.base,y.base+y.count,T(-12345));
        std::fill(z.base,z.base+z.count,T(-12345));
        for(std::size_t i=0;i<o.n+2;++i) {
            x.p[i*o.stride]=input<T>(i,false,o.pattern);
            y.p[i*o.stride]=input<T>(i,true,o.pattern);
        }
    };
    auto invoke=[&]()->T {
        if(kind==5) {
            if constexpr(std::is_same_v<T,float>)return strict_dot_f32(x.p,y.p,o.n,o.stride);
            else return strict_dot_f64(x.p,y.p,o.n,o.stride);
        }
        if constexpr(std::is_same_v<T,float>)return kernel_f32(kind,x.p,y.p,z.p,o.n,o.stride,o.shift==0);
        else return kernel_f64(kind,x.p,y.p,z.p,o.n,o.stride,o.shift==0);
    };
    reset();
    T value=invoke();
    long double max_error=0,sum=0,correction=0,sum_abs=0;
    const long double u=std::numeric_limits<T>::epsilon()/2.0L;
    long double tolerance=16*u;
    if(kind==1 || kind==5) {
        for(std::size_t i=0;i<o.n;++i) {
            long double term=static_cast<long double>(x.p[i*o.stride])*y.p[i*o.stride];
            long double adjusted=term-correction, next=sum+adjusted;
            correction=(next-sum)-adjusted;sum=next;sum_abs+=std::abs(term);
        }
        long double nu=(static_cast<long double>(o.n)+2)*u;
        // A conservative serial summation bound; unavailable above nu >= 1.
        if(nu>=1)throw std::runtime_error("dot N too large for a finite forward-error bound; reduce N");
        tolerance=std::max(16*u,(nu/(1-nu))*sum_abs);
        max_error=std::abs(static_cast<long double>(value)-sum);
        if(!std::isfinite(value) || max_error>tolerance)throw std::runtime_error("dot reference validation failed");
    } else {
        for(std::size_t i=0;i<o.n;++i) {
            auto j=i*o.stride;
            long double a=x.p[j],b=input<T>(i,true,o.pattern), expected;
            T actual;
            if(kind==0){expected=0.125L*a+b;actual=y.p[j];}
            else if(kind==2){expected=a*b;actual=z.p[j];}
            else if(kind==3){expected=0.25L*a+0.5L*x.p[j+o.stride]+0.25L*x.p[j+2*o.stride];actual=z.p[j];}
            else {expected=1.25L*a;actual=y.p[j];}
            auto error=std::abs(static_cast<long double>(actual)-expected);
            max_error=std::max(max_error,error);
            if(!std::isfinite(actual) || error>tolerance*std::max(1.0L,std::abs(expected)))
                throw std::runtime_error("elementwise reference validation failed");
        }
    }
    // Verify every input, stride hole, halo, and guard after the untimed call.
    for(std::size_t j=0;j<x.count;++j) {
        bool logical=j>=o.shift && (j-o.shift)%o.stride==0 && (j-o.shift)/o.stride<o.n+2;
        std::size_t i=logical?(j-o.shift)/o.stride:0;
        T xv=logical?input<T>(i,false,o.pattern):T(-12345);
        T yv=logical?input<T>(i,true,o.pattern):T(-12345);
        if(x.base[j]!=xv)throw std::runtime_error("input/guard corruption");
        bool writable=logical && i<o.n;
        if((kind!=0 && kind!=4) || !writable)
            if(y.base[j]!=yv)throw std::runtime_error("y guard/input corruption");
        if((kind!=2 && kind!=3) || !writable)
            if(z.base[j]!=T(-12345))throw std::runtime_error("z guard corruption");
    }
    if(o.validate_only) {std::cout<<"PASS,"<<BUILD_VARIANT<<','<<o.kernel<<','<<o.dtype<<','<<o.n<<','<<o.stride<<','<<o.shift<<','<<double(max_error)<<'\n';return 0;}
    reset();
    for(int i=0;i<3;++i)sink=double(invoke());
    std::size_t iterations=1;
    using Clock=std::chrono::steady_clock;
    // Calibrate batch length, keeping resetting and validation out of timing.
    for(int attempts=0;attempts<15;++attempts) {
        reset(); auto begin=Clock::now();T result=0;
        for(std::size_t i=0;i<iterations;++i)result=invoke();
        double seconds=std::chrono::duration<double>(Clock::now()-begin).count();sink=double(result);
        if(seconds>=o.seconds*0.85)break;
        double factor=std::min(10.0,std::max(2.0,o.seconds/std::max(seconds,1e-9)));
        iterations=std::min<std::size_t>(100000000, std::size_t(iterations*factor)+1);
    }
    Cycles counter;
    std::cout<<"variant,kernel,dtype,n,stride,shift,pattern,sample,iterations,seconds,core_cycles,tsc_ticks,validation_max_abs_error,validation_bound,checksum\n";
    std::cout<<std::setprecision(17);
    for(int sample=0;sample<o.samples;++sample) {
        reset(); // page faults and initialization excluded; this is a warm-reuse experiment
        sink=double(invoke());
        counter.start(); auto t0=tsc();auto begin=Clock::now();T result=0;
        for(std::size_t i=0;i<iterations;++i) result=invoke();
        auto end=Clock::now();auto t1=tsc();double cycles=counter.stop();
        // Observe outputs OUTSIDE the timed interval. Separate translation units,
        // no LTO, and external calls prevent deleting repeated work.
        long double checksum=result;
        if(kind!=1 && kind!=5) {
            T* out=(kind==0 || kind==4)?y.p:z.p;
            for(std::size_t i=0;i<o.n;++i)checksum+=out[i*o.stride];
        }
        sink=double(checksum);
        if(!std::isfinite(sink))throw std::runtime_error("nonfinite timed output");
        std::cout<<BUILD_VARIANT<<','<<o.kernel<<','<<o.dtype<<','<<o.n<<','<<o.stride<<','<<o.shift<<','<<o.pattern<<','<<sample<<','<<iterations<<','<<std::chrono::duration<double>(end-begin).count()<<',';
        if(cycles>=0)std::cout<<cycles;
        std::cout<<','<<t1-t0<<','<<double(max_error)<<','<<double(tolerance)<<','<<double(checksum)<<'\n';
    }
    return 0;
}
int main(int argc,char** argv) {
    try {
        auto o=parse(argc,argv);int kind=-1;
        const std::vector<std::string> names={"saxpy","dot","mul","stencil","bandwidth","strictdot"};
        auto it=std::find(names.begin(),names.end(),o.kernel);
        if(it==names.end())throw std::runtime_error("unknown kernel");
        kind=int(it-names.begin());
        return o.dtype=="f32"?run<float>(o,kind):run<double>(o,kind);
    } catch(const std::exception& e){std::cerr<<"ERROR: "<<e.what()<<'\n';return 1;}
}
