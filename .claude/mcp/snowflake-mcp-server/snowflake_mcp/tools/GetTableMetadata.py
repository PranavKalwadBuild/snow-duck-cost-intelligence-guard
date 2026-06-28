from typing import Optional, Any, Dict, List


class GetTableMetadata:
    def get_table_metadata(self, table_name: str, database_name: Optional[str] = None, schema_name: Optional[str] = None) -> Dict[str, Any]:
        """Get metadata about a specific table."""
        # Build fully qualified table name
        parts = []
        if database_name:
            parts.append(database_name)
        if schema_name:
            parts.append(schema_name)
        parts.append(table_name)

        full_table_name = '.'.join(parts)

        conn = self.verify_link()
        with conn.cursor() as cursor:
            # Get column information
            cursor.execute(f"DESCRIBE TABLE {full_table_name}")
            col_names = [col[0] for col in cursor.description]
            rows = cursor.fetchall()
            columns = [dict(zip(col_names, row)) for row in rows]

            # Get row count and approximate size
            try:
                cursor.execute(f"SELECT COUNT(*) as row_count FROM {full_table_name}")
                row_count_row = cursor.fetchone()
                row_count = row_count_row[0] if row_count_row else 0
            except:
                row_count = 0

            # Get approximate size (this is simplified - real size calculation is more complex)
            size_bytes = 0  # Placeholder - could calculate from storage metrics if needed

        return {
            'status': 'success',
            'table_name': full_table_name,
            'columns': columns,
            'row_count': row_count,
            'size_bytes': size_bytes
        }