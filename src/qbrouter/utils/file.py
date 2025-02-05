import os


def are_hardlinked(f1, f2):
    if not (os.path.isfile(f1) and os.path.isfile(f2)):
        return False
    return os.path.samefile(f1, f2) or (os.stat(f1).st_ino == os.stat(f2).st_ino)
