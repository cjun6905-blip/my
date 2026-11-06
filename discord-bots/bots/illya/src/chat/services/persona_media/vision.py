from pathlib import Path
def decode_memory_available():
    """Headroom check before large allocations; no forced GC or data eviction."""
    try:
        fields = {line.split(':')[0]: int(line.split()[1])
                  for line in Path('/proc/meminfo').read_text().splitlines()
                  if line.startswith('MemAvailable:')}
        if fields.get('MemAvailable', 1024 * 1024) < 192 * 1024:
            return False
        # Support cgroup v2 and v1 without inspecting process environments.
        for maximum, current in (
                ('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory.current'),
                ('/sys/fs/cgroup/memory/memory.limit_in_bytes',
                 '/sys/fs/cgroup/memory/memory.usage_in_bytes')):
            if Path(maximum).is_file() and Path(current).is_file():
                value = Path(maximum).read_text().strip()
                if value != 'max' and int(value) - int(Path(current).read_text()) < 112 * 1024 * 1024:
                    return False
                break
    except (OSError, ValueError):
        # Other platforms retain the fixed bounded decoder, pixel and byte caps.
        pass
    return True
