use pse::{Config, Engine};

fn main() -> Result<(), pse::Error> {
    let mut engine = Engine::new(Config::preset_streaming())?;
    for tick in 0..120 {
        let batch = vec![format!("sample-{tick}").into_bytes(); 8];
        let step = engine.step(&batch)?;
        if let Some(crystal) = step.crystal {
            println!(
                "tick {}: {} region vertices",
                step.tick,
                crystal.region.len()
            );
        }
    }
    println!("{:?}", engine.statistics());
    Ok(())
}
