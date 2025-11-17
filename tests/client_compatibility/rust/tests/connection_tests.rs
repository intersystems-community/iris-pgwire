use tokio_postgres::{Client, NoTls, Config};
use std::env;

/// Get PostgreSQL connection configuration from environment
fn get_connection_config() -> Config {
    let host = env::var("PGWIRE_HOST").unwrap_or_else(|_| "localhost".to_string());
    let port = env::var("PGWIRE_PORT")
        .unwrap_or_else(|_| "5432".to_string())
        .parse::<u16>()
        .unwrap_or(5432);
    let dbname = env::var("PGWIRE_DATABASE").unwrap_or_else(|_| "USER".to_string());
    let user = env::var("PGWIRE_USERNAME").unwrap_or_else(|_| "test_user".to_string());
    let password = env::var("PGWIRE_PASSWORD").unwrap_or_else(|_| "test".to_string());

    let mut config = Config::new();
    config
        .host(&host)
        .port(port)
        .dbname(&dbname)
        .user(&user)
        .password(&password);

    config
}

/// Establish connection helper
async fn connect() -> Result<Client, Box<dyn std::error::Error>> {
    let config = get_connection_config();
    let (client, connection) = config.connect(NoTls).await?;

    // Spawn connection handler
    tokio::spawn(async move {
        if let Err(e) = connection.await {
            eprintln!("Connection error: {}", e);
        }
    });

    Ok(client)
}

#[tokio::test]
async fn test_basic_connection() {
    // GIVEN: PGWire server is running
    // WHEN: Attempting to connect
    let client = connect().await.expect("should establish connection");

    // THEN: Connection should work and execute simple query
    let row = client
        .query_one("SELECT 1", &[])
        .await
        .expect("should execute simple query");

    let result: i32 = row.get(0);
    assert_eq!(result, 1, "should return 1");
}

#[tokio::test]
async fn test_connection_string_parsing() {
    // GIVEN: Connection string format
    let conn_str = format!(
        "host={} port={} dbname={} user={} password={}",
        env::var("PGWIRE_HOST").unwrap_or_else(|_| "localhost".to_string()),
        env::var("PGWIRE_PORT").unwrap_or_else(|_| "5432".to_string()),
        env::var("PGWIRE_DATABASE").unwrap_or_else(|_| "USER".to_string()),
        env::var("PGWIRE_USERNAME").unwrap_or_else(|_| "test_user".to_string()),
        env::var("PGWIRE_PASSWORD").unwrap_or_else(|_| "test".to_string())
    );

    // WHEN: Connecting with connection string
    let (client, connection) = tokio_postgres::connect(&conn_str, NoTls)
        .await
        .expect("should connect with connection string");

    tokio::spawn(async move {
        if let Err(e) = connection.await {
            eprintln!("Connection error: {}", e);
        }
    });

    // THEN: Connection succeeds
    let row = client.query_one("SELECT 1", &[]).await.expect("should query");
    let result: i32 = row.get(0);
    assert_eq!(result, 1);
}

#[tokio::test]
async fn test_multiple_sequential_connections() {
    // GIVEN: Multiple connection attempts
    // WHEN: Creating 5 sequential connections
    for i in 1..=5 {
        let client = connect().await.expect("should connect");

        // THEN: Each connection should work
        let row = client
            .query_one("SELECT $1::int4", &[&i])
            .await
            .expect("should execute query");

        let result: i32 = row.get(0);
        assert_eq!(result, i, "should return {}", i);
    }
}

#[tokio::test]
async fn test_server_version() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Querying server version
    let row = client
        .query_one("SELECT version()", &[])
        .await
        .expect("should get version");

    // THEN: Should return version string
    let version: String = row.get(0);
    assert!(
        version.contains("PostgreSQL") || version.contains("IRIS"),
        "Version should mention PostgreSQL or IRIS: {}",
        version
    );
    println!("Server version: {}", version);
}

#[tokio::test]
async fn test_connection_error_handling() {
    // GIVEN: Invalid connection parameters
    let mut config = Config::new();
    config
        .host("invalid-host-that-does-not-exist")
        .port(9999)
        .dbname("invalid_db")
        .user("invalid_user")
        .password("invalid_password");

    // WHEN: Attempting to connect
    let result = config.connect(NoTls).await;

    // THEN: Connection should fail gracefully
    assert!(result.is_err(), "should fail to connect to invalid host");
}

#[tokio::test]
async fn test_query_after_connection() {
    // GIVEN: Established connection
    let client = connect().await.expect("should connect");

    // WHEN: Executing multiple queries
    let row1 = client.query_one("SELECT 'hello'", &[]).await.expect("query 1");
    let row2 = client.query_one("SELECT 'world'", &[]).await.expect("query 2");

    // THEN: Both queries should succeed
    let result1: String = row1.get(0);
    let result2: String = row2.get(0);
    assert_eq!(result1, "hello");
    assert_eq!(result2, "world");
}
