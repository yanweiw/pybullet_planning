from os.path import join, abspath, dirname, isdir, isfile
import sys

current_dir = abspath(dirname(__file__))

# print(current_dir)
KITCHEN_WORLD = sys.path[0]
# PARTNET_PATH = join('..', '..', 'dataset')
ASSET_PATH = join(sys.path[0], 'assets')

# ## NVIDIA desktop
# if 'zhutiany' in current_dir:
#     KITCHEN_WORLD = join('..', '..', '..', 'kitchen-worlds')
#     PARTNET_PATH = join('..', '..', 'data', 'partnet_mobility_v0', 'dataset')
#     ASSET_PATH = join('..', '..', '..', 'kitchen-worlds', 'assets')
#     # ASSET_PATH = join('..', 'assets')

# ## Macbook Pro
# else:
#     KITCHEN_WORLD = join('..', '..', '..', 'PyBullet', 'kitchen-worlds')
#     PARTNET_PATH = join('..', '..', 'dataset')
#     ASSET_PATH = join('..', 'assets')