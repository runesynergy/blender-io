
import os

def export_vector(a):
    x = int(a[0] + 0.5)
    y = int(-a[2] + 0.5)
    z = int(a[1] + 0.5)
    return (x, y, z)

def filename_without_extension(filepath):
    filename, _ = os.path.splitext(os.path.basename(filepath))
    return filename
