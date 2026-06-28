"""
Machine specifications utility for the DuckDB/Snowflake agent.
"""
import os
import psutil
import platform
from typing import Dict, Any

def get_machine_specs() -> Dict[str, Any]:
    """
    Get machine specifications for informed decision making.

    Returns:
        Dictionary containing CPU, memory, disk, and system information
    """
    try:
        # CPU information
        cpu_count = psutil.cpu_count(logical=False)  # Physical cores
        cpu_count_logical = psutil.cpu_count(logical=True)  # Logical cores
        cpu_freq = psutil.cpu_freq()
        cpu_percent = psutil.cpu_percent(interval=1)

        # Memory information
        memory = psutil.virtual_memory()
        total_memory = memory.total
        available_memory = memory.available
        used_memory = memory.used
        memory_percent = memory.percent

        # Disk information
        disk = psutil.disk_usage('/')
        total_disk = disk.total
        free_disk = disk.free
        used_disk = disk.used
        disk_percent = (used_disk / total_disk) * 100

        # System information
        system = platform.system()
        system_release = platform.release()
        system_version = platform.version()
        processor = platform.processor()

        specs = {
            'cpu_count': cpu_count,
            'cpu_count_logical': cpu_count_logical,
            'cpu_freq_mhz': cpu_freq.current if cpu_freq else 0,
            'cpu_percent': cpu_percent,
            'total_memory': total_memory,
            'available_memory': available_memory,
            'used_memory': used_memory,
            'memory_percent': memory_percent,
            'total_disk': total_disk,
            'free_disk': free_disk,
            'used_disk': used_disk,
            'disk_percent': disk_percent,
            'system': system,
            'system_release': system_release,
            'system_version': system_version,
            'processor': processor,
            'platform': platform.platform()
        }

        return specs

    except Exception as e:
        # Fallback to basic specs if psutil fails
        return {
            'cpu_count': os.cpu_count() or 1,
            'cpu_count_logical': os.cpu_count() or 1,
            'cpu_freq_mhz': 0,
            'cpu_percent': 0,
            'total_memory': 4 * 1024**3,  # Assume 4GB total
            'available_memory': 2 * 1024**3,  # Assume 2GB available
            'used_memory': 0,
            'memory_percent': 0,
            'total_disk': 100 * 1024**3,  # Assume 100GB disk
            'free_disk': 50 * 1024**3,
            'used_disk': 50 * 1024**3,
            'disk_percent': 50,
            'system': platform.system(),
            'system_release': platform.release(),
            'system_version': platform.version(),
            'processor': platform.processor(),
            'platform': platform.platform(),
            'error': str(e)
        }