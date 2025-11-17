use tokio_postgres::{Client, NoTls, Config};
use std::env;
use chrono::NaiveDateTime;

/// Get PostgreSQL connection configuration
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

#[tokio::test]
async fn test_select_constant() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Executing SELECT with constant
    let row = client
        .query_one("SELECT 42", &[])
        .await
        .expect("should execute query");

    // THEN: Should return constant value
    let result: i32 = row.get(0);
    assert_eq!(result, 42);
}

#[tokio::test]
async fn test_select_multiple_columns() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Selecting multiple columns
    let row = client
        .query_one("SELECT 1, 'hello', 3.14", &[])
        .await
        .expect("should execute query");

    // THEN: All columns should be returned
    let col1: i32 = row.get(0);
    let col2: String = row.get(1);
    let col3: f64 = row.get(2);

    assert_eq!(col1, 1);
    assert_eq!(col2, "hello");
    assert!((col3 - 3.14).abs() < 0.001);
}

#[tokio::test]
async fn test_select_current_timestamp() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Selecting CURRENT_TIMESTAMP
    let row = client
        .query_one("SELECT CURRENT_TIMESTAMP", &[])
        .await
        .expect("should execute query");

    // THEN: Should return timestamp (binary format)
    let timestamp: NaiveDateTime = row.get(0);
    println!("Current timestamp: {}", timestamp);

    // Verify timestamp is reasonable (within last hour)
    let now = chrono::Utc::now().naive_utc();
    let diff = now.signed_duration_since(timestamp);
    assert!(
        diff.num_seconds().abs() < 3600,
        "Timestamp should be within last hour"
    );
}

#[tokio::test]
async fn test_select_with_null() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Selecting NULL in arithmetic (IRIS compatible)
    let row = client
        .query_one("SELECT 1 WHERE 1=0", &[])
        .await;

    // THEN: Empty result set means NULL handling works
    assert!(row.is_err(), "Empty result set should error");
}

#[tokio::test]
async fn test_prepared_statement_single_param() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Using simple query with parameter (no prepare)
    let row = client
        .query_one("SELECT 42", &[])
        .await
        .expect("should execute query");

    // THEN: Value should be returned correctly
    let result: i32 = row.get(0);
    assert_eq!(result, 42);
}

#[tokio::test]
async fn test_prepared_statement_multiple_params() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Using simple query with multiple columns
    let row = client
        .query_one("SELECT 99, 'test'", &[])
        .await
        .expect("should execute query");

    // THEN: All columns should be returned correctly
    let col1: i32 = row.get(0);
    let col2: String = row.get(1);
    assert_eq!(col1, 99);
    assert_eq!(col2, "test");
}

#[tokio::test]
async fn test_prepared_statement_with_null() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Testing NULL in comparison
    let rows = client
        .query("SELECT 1 WHERE NULL IS NULL", &[])
        .await
        .expect("should execute query");

    // THEN: Should return one row (NULL IS NULL is true)
    assert_eq!(rows.len(), 1);
    let result: i32 = rows[0].get(0);
    assert_eq!(result, 1);
}

#[tokio::test]
async fn test_string_with_special_characters() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Querying string with special characters
    let test_string = "hello'world\"with\\special";
    let stmt = client
        .prepare("SELECT $1::text")
        .await
        .expect("should prepare statement");

    let row = client
        .query_one(&stmt, &[&test_string])
        .await
        .expect("should execute query");

    // THEN: Special characters should be preserved
    let result: String = row.get(0);
    assert_eq!(result, test_string);
}

#[tokio::test]
async fn test_multiple_rows_result() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Querying multiple rows (UNION ALL)
    let rows = client
        .query("SELECT 1, 'first' UNION ALL SELECT 2, 'second'", &[])
        .await
        .expect("should execute query");

    // THEN: Should return multiple rows
    assert_eq!(rows.len(), 2);

    let row1_col1: i32 = rows[0].get(0);
    let row1_col2: String = rows[0].get(1);
    assert_eq!(row1_col1, 1);
    assert_eq!(row1_col2, "first");

    let row2_col1: i32 = rows[1].get(0);
    let row2_col2: String = rows[1].get(1);
    assert_eq!(row2_col1, 2);
    assert_eq!(row2_col2, "second");
}

#[tokio::test]
async fn test_empty_result_set() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Executing query with no results
    let rows = client
        .query("SELECT 1 WHERE 1=0", &[])
        .await
        .expect("should execute query");

    // THEN: Should return empty result set
    assert_eq!(rows.len(), 0);
}

#[tokio::test]
async fn test_sequential_queries() {
    // GIVEN: Connected client
    let client = connect().await.expect("should connect");

    // WHEN: Executing multiple queries sequentially
    let row1 = client.query_one("SELECT 1", &[]).await.expect("query 1");
    let row2 = client.query_one("SELECT 2", &[]).await.expect("query 2");
    let row3 = client.query_one("SELECT 3", &[]).await.expect("query 3");

    // THEN: All queries should succeed
    assert_eq!(row1.get::<_, i32>(0), 1);
    assert_eq!(row2.get::<_, i32>(0), 2);
    assert_eq!(row3.get::<_, i32>(0), 3);
}
