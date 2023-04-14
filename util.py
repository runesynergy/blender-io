
import os

def export_vector(a):
    x = +int(a[0] + 0.5)
    y = -int(a[2] + 0.5)
    z = +int(a[1] + 0.5)
    return (x, y, z)

def export_angle(radian_angle, min_value=0, max_value=2047):
    normalized_angle = radian_angle % (2 * math.pi)
    int_angle = int((normalized_angle * 325.94932345220164765467394738691) + 0.5)
    return int_angle    

# expects an ZXY euler
def export_euler(euler):
    return (
        +export_angle(euler[0]),
        +export_angle(euler[1]),
        -export_angle(euler[2]),
    )

def filename_without_extension(filepath):
    filename, _ = os.path.splitext(os.path.basename(filepath))
    return filename
