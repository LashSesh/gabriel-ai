//! Prints the golden fixture of `benches/engine.rs` (whole-state digests of the engine cases and
//! the seeded graph histories) for the arithmetic profile compiled into this build.
#![allow(dead_code)]
#[path = "../benches/engine.rs"]
mod harness;

fn main() {
    let value = harness::golden();
    println!("{}", serde_json::to_string_pretty(&serde_json::json!({
        "arithmetic_profile": pse_fmath::ARITHMETIC_PROFILE,
        "schema": value["schema"], "engine": value["engine"], "graphs": value["graphs"]})).unwrap());
}
