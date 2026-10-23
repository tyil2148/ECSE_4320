#include "kernels.hpp"

// No OpenMP, intrinsics, threads, or hand-selected vector width. The compiler
// chooses vectorization. Alignment promises are used only with shift == 0.
template<class T, std::size_t S, bool Aligned>
__attribute__((noinline)) T execute(int kind, T* __restrict__ x,
    T* __restrict__ y, T* __restrict__ z, std::size_t n) {
    if constexpr (Aligned) {
        x = static_cast<T*>(__builtin_assume_aligned(x, 64));
        y = static_cast<T*>(__builtin_assume_aligned(y, 64));
        z = static_cast<T*>(__builtin_assume_aligned(z, 64));
    }
    switch (kind) {
    case 0: // SAXPY/AXPY, in place. a is exactly representable in both types.
        for (std::size_t i=0; i<n; ++i) y[i*S] = T(0.125)*x[i*S] + y[i*S];
        return T(0);
    case 1: { // The relaxed build permits reassociation of this reduction.
        T sum = 0;
        for (std::size_t i=0; i<n; ++i) sum += x[i*S]*y[i*S];
        return sum;
    }
    case 2:
        for (std::size_t i=0; i<n; ++i) z[i*S] = x[i*S]*y[i*S];
        return T(0);
    case 3: // x has n+2 logical entries, z has n interior outputs.
        for (std::size_t i=0; i<n; ++i)
            z[i*S] = T(0.25)*x[i*S] + T(0.5)*x[(i+1)*S] + T(0.25)*x[(i+2)*S];
        return T(0);
    case 4: // Single-thread temporal scale, for an attainable bandwidth ceiling.
        // Nontrivial scaling prevents replacement with libc memcpy/non-temporal stores.
        for (std::size_t i=0; i<n; ++i) y[i*S] = T(1.25)*x[i*S];
        return T(0);
    }
    return T(0);
}

template<class T, bool A> T dispatch(int kind, T* x, T* y, T* z,
                                     std::size_t n, std::size_t stride) {
    // Specializing stride makes comparisons meaningful: division/address
    // arithmetic is not inadvertently introduced into the unit-stride loop.
    switch (stride) {
    case 1: return execute<T,1,A>(kind,x,y,z,n);
    case 2: return execute<T,2,A>(kind,x,y,z,n);
    case 4: return execute<T,4,A>(kind,x,y,z,n);
    case 8: return execute<T,8,A>(kind,x,y,z,n);
    }
    return T(0); // The harness rejects unsupported strides.
}
extern "C" float kernel_f32(int k,float* x,float* y,float* z,std::size_t n,std::size_t s,bool a) {
    return a ? dispatch<float,true>(k,x,y,z,n,s) : dispatch<float,false>(k,x,y,z,n,s);
}
extern "C" double kernel_f64(int k,double* x,double* y,double* z,std::size_t n,std::size_t s,bool a) {
    return a ? dispatch<double,true>(k,x,y,z,n,s) : dispatch<double,false>(k,x,y,z,n,s);
}
