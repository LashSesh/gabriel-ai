//! Platform-independent transcendental arithmetic (Gabriel determinism study, ADR-19).
//!
//! Every transcendental function the engine evaluates goes through this trait. By default the
//! implementation is the pure-Rust `libm` crate (a port of musl's libm), so a given input produces
//! the same binary64 result on every platform and toolchain that builds this workspace. The
//! `platform-libm` feature routes the same calls to the C library of the host instead; it exists
//! only to reproduce and explain historical, platform-bound results. Basic IEEE-754 operations
//! (`+`, `-`, `*`, `/`, `sqrt`, `mul_add`, `powi`) are correctly rounded by the standard and are
//! not wrapped.
#![forbid(unsafe_code)]

pub trait Fmath {
    fn dsin(self) -> f64;
    fn dcos(self) -> f64;
    fn dsin_cos(self) -> (f64, f64);
    fn dexp(self) -> f64;
    fn dln(self) -> f64;
    fn dlog2(self) -> f64;
    fn datan2(self, other: f64) -> f64;
    fn dtan(self) -> f64;
    fn dtanh(self) -> f64;
    fn dpowf(self, exponent: f64) -> f64;
}

#[cfg(not(feature = "platform-libm"))]
impl Fmath for f64 {
    #[inline]
    fn dsin(self) -> f64 {
        #[cfg(feature = "study-perturb-sin")]
        {
            // Determinism study only: the result moved by one unit in the last place.
            let value = libm::sin(self);
            return if value >= 0.0 { f64::from_bits(value.to_bits() + 1) } else { f64::from_bits(value.to_bits() - 1) };
        }
        #[cfg(not(feature = "study-perturb-sin"))]
        libm::sin(self)
    }
    #[inline]
    fn dcos(self) -> f64 {
        libm::cos(self)
    }
    #[inline]
    fn dsin_cos(self) -> (f64, f64) {
        libm::sincos(self)
    }
    #[inline]
    fn dexp(self) -> f64 {
        libm::exp(self)
    }
    #[inline]
    fn dln(self) -> f64 {
        libm::log(self)
    }
    #[inline]
    fn dlog2(self) -> f64 {
        libm::log2(self)
    }
    #[inline]
    fn datan2(self, other: f64) -> f64 {
        libm::atan2(self, other)
    }
    #[inline]
    fn dtan(self) -> f64 {
        libm::tan(self)
    }
    #[inline]
    fn dtanh(self) -> f64 {
        libm::tanh(self)
    }
    #[inline]
    fn dpowf(self, exponent: f64) -> f64 {
        libm::pow(self, exponent)
    }
}

#[cfg(feature = "platform-libm")]
impl Fmath for f64 {
    #[inline]
    fn dsin(self) -> f64 {
        self.sin()
    }
    #[inline]
    fn dcos(self) -> f64 {
        self.cos()
    }
    #[inline]
    fn dsin_cos(self) -> (f64, f64) {
        self.sin_cos()
    }
    #[inline]
    fn dexp(self) -> f64 {
        self.exp()
    }
    #[inline]
    fn dln(self) -> f64 {
        self.ln()
    }
    #[inline]
    fn dlog2(self) -> f64 {
        self.log2()
    }
    #[inline]
    fn datan2(self, other: f64) -> f64 {
        self.atan2(other)
    }
    #[inline]
    fn dtan(self) -> f64 {
        self.tan()
    }
    #[inline]
    fn dtanh(self) -> f64 {
        self.tanh()
    }
    #[inline]
    fn dpowf(self, exponent: f64) -> f64 {
        self.powf(exponent)
    }
}

/// The arithmetic profile compiled into this build, for identities and manifests.
pub const ARITHMETIC_PROFILE: &str = if cfg!(feature = "platform-libm") {
    "platform-libm"
} else {
    "pure-rust-libm"
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn functions_are_finite_and_consistent() {
        let x = 0.7_f64;
        let (s, c) = x.dsin_cos();
        assert_eq!(s, x.dsin());
        assert_eq!(c, x.dcos());
        assert!((s * s + c * c - 1.0).abs() < 1e-15);
        assert!((x.dexp().dln() - x).abs() < 1e-15);
        assert_eq!(0.0_f64.datan2(1.0), 0.0);
    }
}
