#pragma once
#include <cstddef>
// Each array is disjoint. n counts outputs, including the stencil's interior outputs.
extern "C" {
float kernel_f32(int kind, float* x, float* y, float* z, std::size_t n,
                 std::size_t stride, bool aligned);
double kernel_f64(int kind, double* x, double* y, double* z, std::size_t n,
                  std::size_t stride, bool aligned);
float strict_dot_f32(const float* x, const float* y, std::size_t n, std::size_t stride);
double strict_dot_f64(const double* x, const double* y, std::size_t n, std::size_t stride);
}
