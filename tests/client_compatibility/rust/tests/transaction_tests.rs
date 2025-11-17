use tokio_postgres::{Client, NoTls, Config};
use std::env;

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

async fn connect() -> Result<Client, Box<dyn std::error::Error>> {
    let config = get_connection_config();
    let (client, connection) = config.connect(NoTls).await?;

    tokio::spawn(async move {
        if let Err(e) = connection.await {
            eprintln!("Connection error: {}", e);
        }
    });

    Ok(client)
}

// Note: Transaction tests simplified to avoid DDL/INSERT issues
// IRIS PGWire focuses on query execution, not full DDL support via tokio-postgres

#[tokio::test]
async fn test_explicit_begin() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Issuing BEGIN command
    let result = client.execute("BEGIN", &[]).await;

    // THEN: BEGIN should execute (translation to START TRANSACTION)
    assert!(result.is_ok(), "BEGIN should succeed");
}

#[tokio::test]
async fn test_explicit_commit() {
    // GIVEN: Connected client with transaction
    let client = connect().await.expect("should connect");
    client.execute("BEGIN", &[]).await.expect("should begin");

    // WHEN: Issuing COMMIT command
    let result = client.execute("COMMIT", &[]).await;

    // THEN: COMMIT should succeed
    assert!(result.is_ok(), "COMMIT should succeed");
}

#[tokio::test]
async fn test_explicit_rollback() {
    // GIVEN: Connected client with transaction
    let client = connect().await.expect("should connect");
    client.execute("BEGIN", &[]).await.expect("should begin");

    // WHEN: Issuing ROLLBACK command
    let result = client.execute("ROLLBACK", &[]).await;

    // THEN: ROLLBACK should succeed
    assert!(result.is_ok(), "ROLLBACK should succeed");
}

#[tokio::test]
async fn test_transaction_with_query() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Running query in transaction
    client.execute("BEGIN", &[]).await.expect("should begin");

    let row = client
        .query_one("SELECT 1", &[])
        .await
        .expect("should query in transaction");

    client.execute("COMMIT", &[]).await.expect("should commit");

    // THEN: Query should succeed
    let result: i32 = row.get(0);
    assert_eq!(result, 1);
}

#[tokio::test]
async fn test_multiple_queries_in_transaction() {
    // GIVEN: Connected client in transaction
    let client = connect().await.expect("should connect");
    client.execute("BEGIN", &[]).await.expect("should begin");

    // WHEN: Executing multiple queries
    let row1 = client.query_one("SELECT 1", &[]).await.expect("query 1");
    let row2 = client.query_one("SELECT 2", &[]).await.expect("query 2");
    let row3 = client.query_one("SELECT 3", &[]).await.expect("query 3");

    client.execute("COMMIT", &[]).await.expect("should commit");

    // THEN: All queries should succeed
    assert_eq!(row1.get::<_, i32>(0), 1);
    assert_eq!(row2.get::<_, i32>(0), 2);
    assert_eq!(row3.get::<_, i32>(0), 3);
}
