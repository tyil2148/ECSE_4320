#include "kernels.hpp"
// Compiled without fast-math or contraction in ALL variants. This intentionally
// preserves ordered summation and supplies an evidence-based failure candidate.
extern "C" __attribute__((noinline)) float strict_dot_f32(const float* __restrict__ x,
    const float* __restrict__ y, std::size_t n, std::size_t s) {
    float sum=0;
    for(std::size_t i=0;i<n;++i) sum += x[i*s]*y[i*s];
    return sum;
}
extern "C" __attribute__((noinline)) double strict_dot_f64(const double* __restrict__ x,
    const double* __restrict__ y, std::size_t n, std::size_t s) {
    double sum=0;
    for(std::size_t i=0;i<n;++i) sum += x[i*s]*y[i*s];
    return sum;
}
