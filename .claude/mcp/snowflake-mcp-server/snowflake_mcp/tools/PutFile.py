from typing import Optional, Any, Dict, List
import os


class PutFile:
    def put_file(self, local_file_path: str, stage_path: str, auto_compress: bool = True, overwrite: bool = True) -> Dict[str, Any]:
        """Upload a file to a Snowflake stage."""
        # Validate local file exists
        if not os.path.exists(local_file_path):
            raise FileNotFoundError(f"Local file not found: {local_file_path}")

        # Get file size for reporting
        file_size = os.path.getsize(local_file_path)

        conn = self.verify_link()
        with conn.cursor() as cursor:
            # Use Snowflake's PUT command to upload file to stage
            cursor.put(
                local_file_path,
                stage_path,
                auto_compress=auto_compress,
                overwrite=overwrite
            )

        return {
            "status": "success",
            "message": f"File uploaded to {stage_path}",
            "local_file_path": local_file_path,
            "stage_path": stage_path,
            "bytes_transferred": file_size,
            "auto_compress": auto_compress,
            "overwrite": overwrite
        }