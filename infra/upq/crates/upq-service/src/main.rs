use std::net::SocketAddr;

use upq_service::app::build_router;

#[tokio::main]
async fn main() {
    let app = build_router();
    let addr = SocketAddr::from(([127, 0, 0, 1], 23333));

    let listener = match tokio::net::TcpListener::bind(addr).await {
        Ok(listener) => listener,
        Err(error) => {
            eprintln!("failed to bind listener: {error}");
            return;
        }
    };

    if let Err(error) = axum::serve(listener, app).await {
        eprintln!("server failed: {error}");
    }
}
