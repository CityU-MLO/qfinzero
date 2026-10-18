use std::net::SocketAddr;

use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};
use upq_service::app::build_router;

#[tokio::main]
async fn main() {
    // Load .env file if present
    if let Err(e) = dotenvy::dotenv() {
        tracing::debug!("No .env file found or failed to load: {}", e);
    }

    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "upq_service=info,tower_http=info".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    let app = build_router();
    let port = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(19350);
    // Loopback by default: clients reach UPQ through the hub (auth, /svc/upq).
    // Set UPQ_HOST=0.0.0.0 to expose it directly.
    let host: std::net::IpAddr = std::env::var("UPQ_HOST")
        .ok()
        .and_then(|h| h.parse().ok())
        .unwrap_or(std::net::IpAddr::from([127, 0, 0, 1]));
    let addr = SocketAddr::from((host, port));

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
