use std::net::SocketAddr;

use upq_service::app::build_router;

#[tokio::main]
async fn main() {
    let app = build_router();
    let port = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(23333);
    let addr = SocketAddr::from(([0, 0, 0, 0], port));

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
