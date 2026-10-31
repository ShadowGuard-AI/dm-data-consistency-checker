import argparse
import logging
import sqlite3
import sys
from typing import List, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def setup_argparse() -> argparse.ArgumentParser:
    """
    Sets up the argument parser for the command-line interface.

    Returns:
        argparse.ArgumentParser: The argument parser object.
    """
    parser = argparse.ArgumentParser(
        description="Verifies referential integrity across masked datasets."
    )
    parser.add_argument(
        "--db_path1",
        required=True,
        help="Path to the first SQLite database file.",
    )
    parser.add_argument(
        "--db_path2",
        required=True,
        help="Path to the second SQLite database file (masked version).",
    )
    parser.add_argument(
        "--table_name",
        required=True,
        help="Name of the table to check for referential integrity.",
    )
    parser.add_argument(
        "--foreign_key_column",
        required=True,
        help="Name of the foreign key column in the table.",
    )
    parser.add_argument(
        "--parent_table",
        required=True,
        help="Name of the parent table referenced by the foreign key.",
    )
    parser.add_argument(
        "--parent_key_column",
        required=True,
        help="Name of the primary key column in the parent table.",
    )

    return parser


def execute_query(db_path: str, query: str) -> List[Tuple]:
    """
    Executes an SQL query against the specified database and returns the results.

    Args:
        db_path (str): Path to the SQLite database file.
        query (str): The SQL query to execute.

    Returns:
        List[Tuple]: A list of tuples representing the query results.  Empty list if query fails.
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()
        return results
    except sqlite3.Error as e:
        logging.error(f"Error executing query on {db_path}: {e}")
        return []


def check_referential_integrity(
    db_path1: str,
    db_path2: str,
    table_name: str,
    foreign_key_column: str,
    parent_table: str,
    parent_key_column: str,
) -> bool:
    """
    Checks referential integrity between two databases after masking.

    Args:
        db_path1 (str): Path to the original database.
        db_path2 (str): Path to the masked database.
        table_name (str): Name of the table with the foreign key.
        foreign_key_column (str): Name of the foreign key column.
        parent_table (str): Name of the parent table.
        parent_key_column (str): Name of the parent table's primary key column.

    Returns:
        bool: True if referential integrity is maintained, False otherwise.
    """

    # Build the query to find orphaned foreign keys in the masked database
    query = f"""
    SELECT COUNT(*)
    FROM {table_name} t
    LEFT JOIN {parent_table} p ON t.{foreign_key_column} = p.{parent_key_column}
    WHERE t.{foreign_key_column} IS NOT NULL AND p.{parent_key_column} IS NULL;
    """

    results = execute_query(db_path2, query)

    if not results:
        logging.error("Failed to execute the query to check referential integrity.")
        return False

    orphaned_count = results[0][0]

    if orphaned_count > 0:
        logging.warning(f"Referential integrity check failed. Found {orphaned_count} orphaned foreign keys.")

        # Optionally, log some examples of orphaned keys for further investigation.
        example_query = f"""
            SELECT t.{foreign_key_column}
            FROM {table_name} t
            LEFT JOIN {parent_table} p ON t.{foreign_key_column} = p.{parent_key_column}
            WHERE t.{foreign_key_column} IS NOT NULL AND p.{parent_key_column} IS NULL
            LIMIT 5;
        """
        example_results = execute_query(db_path2, example_query)
        if example_results:
            logging.warning(f"Example orphaned keys: {example_results}")
        return False

    logging.info("Referential integrity check passed.")
    return True


def validate_first_database(db_path: str, table_name: str, foreign_key_column: str, parent_table: str, parent_key_column: str) -> bool:
    """Open the first database and check it holds the named tables and columns.

    Returns True only when the file reads as a SQLite database and both
    named tables exist with the named columns present.
    """
    try:
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}
            for table, column in ((table_name, foreign_key_column), (parent_table, parent_key_column)):
                if table not in tables:
                    logging.error(f"First database {db_path} does not contain table: {table}")
                    return False
                safe = table.replace('"', '""')
                cursor.execute(f'PRAGMA table_info("{safe}");')
                columns = {row[1] for row in cursor.fetchall()}
                if column not in columns:
                    logging.error(f"First database {db_path} table {table} does not contain column: {column}")
                    return False
        finally:
            conn.close()
    except sqlite3.Error as e:
        logging.error(f"First database {db_path} cannot be read as a SQLite database: {e}")
        return False
    return True


def validate_database_path(db_path: str) -> bool:
    """
    Validates if the provided database path exists.

    Args:
        db_path (str): Path to the database file.

    Returns:
        bool: True if the database exists, False otherwise.
    """
    import os

    if not os.path.exists(db_path):
        logging.error(f"Database file not found: {db_path}")
        return False
    return True


def main():
    """
    Main function to execute the data consistency checker.
    """
    parser = setup_argparse()
    args = parser.parse_args()

    if not validate_database_path(args.db_path1):
        sys.exit(1)
    if not validate_database_path(args.db_path2):
        sys.exit(1)
    # The first database is opened and validated as a readable SQLite
    # database holding the named tables and columns. The orphan query
    # itself still runs against db_path2, the masked copy.
    if not validate_first_database(args.db_path1, args.table_name, args.foreign_key_column, args.parent_table, args.parent_key_column):
        print("Data consistency check failed.")
        sys.exit(1)

    # Validate input arguments (table and column names). Ideally, these would
    # be validated against the schema of the database files, but that requires
    # significantly more complex code, so we're skipping it here for simplicity,
    # in favor of letting sqlite3 raise an error if a table or column does not exist.

    try:
        if check_referential_integrity(
            args.db_path1,
            args.db_path2,
            args.table_name,
            args.foreign_key_column,
            args.parent_table,
            args.parent_key_column,
        ):
            print("Data consistency check passed.")
        else:
            print("Data consistency check failed.")
            sys.exit(1)  # Exit with an error code
    except Exception as e:
        logging.exception("An unexpected error occurred:")
        print(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Example usage:
    #   python main.py --db_path1 original.db --db_path2 masked.db --table_name orders --foreign_key_column customer_id --parent_table customers --parent_key_column id
    # An earlier version built dummy original.db and masked.db files in
    # the caller's working directory before main ran. A read-only checker
    # has no business creating databases next to the ones it inspects, and
    # the leftovers could be mistaken for real data on the next run.
    main()