use std::env;
use std::error::Error;
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn Error>> {
    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR")?);
    let workspace_root = manifest_dir
        .parent()
        .and_then(|path| path.parent())
        .ok_or("session_proto build.rs could not locate the workspace root")?;
    let proto_root = workspace_root.join("proto");
    let proto_file = proto_root.join("session.proto");

    let protoc = protoc_bin_vendored::protoc_bin_path()?;
    env::set_var("PROTOC", protoc);

    prost_build::Config::new().compile_protos(&[proto_file], &[proto_root])?;

    println!(
        "cargo:rerun-if-changed={}",
        workspace_root.join("proto/session.proto").display()
    );
    Ok(())
}
