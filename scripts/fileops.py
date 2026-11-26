"""Publish finished files without ever replacing an existing one."""
import os
import shutil


def publish_file(staged, destination):
    """Expose a verified file at destination; raise FileExistsError if it exists.

    A hard link publishes the file in one step. Some drives cannot hold hard links
    (exFAT, FAT32, many network and sync folders); there the file is copied into a
    newly created destination, which still refuses to overwrite anything.
    """
    try:
        os.link(staged, destination)
        return
    except FileExistsError:
        raise
    except OSError:
        pass
    with open(destination, "xb") as out:
        try:
            with open(staged, "rb") as source:
                shutil.copyfileobj(source, out)
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            out.close()
            os.unlink(destination)
            raise
