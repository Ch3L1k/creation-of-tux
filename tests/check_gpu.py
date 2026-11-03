"""Check invariants in GPU-rendered frames; does not touch the live desktop."""
from pathlib import Path
import subprocess
import numpy as np
from PIL import Image
root=Path(__file__).resolve().parents[1]
import tempfile
temporary=tempfile.TemporaryDirectory(prefix="tux-gpu-check-")
preview=Path(temporary.name)
frames=[]
for phase in (0,55,90,180):
    path=preview/f'check-{phase}.png'
    subprocess.run([str(root/'build/creation-ascii'),'--phase',str(phase),'--snapshot',str(path)],check=True)
    frames.append(np.asarray(Image.open(path)))
first=frames[0]
assert first.shape==(1080,1920,4)
assert np.all(first[:,:,3]==255), 'Wallpaper must be opaque'
# The complete perspective projection of Tux fits safely in the middle quarter.
for frame in frames[1:]:
    assert np.array_equal(first[:,:720],frame[:,:720]), 'Adam moved'
    assert np.array_equal(first[:,1200:],frame[:,1200:]), 'Right figure moved'
    assert not np.array_equal(first[:,720:1200],frame[:,720:1200]), 'Tux is not rotating'
# The silhouette now has thickness: edge-on remains visible but narrow.
front=frames[0][300:800,720:1200,:3]
edge=frames[2][300:800,720:1200,:3]
front_ink=np.count_nonzero(front.max(axis=2)>35)
edge_ink=np.count_nonzero(edge.max(axis=2)>35)
assert 100<edge_ink<front_ink*.55, (front_ink,edge_ink)
path=preview/'shimmer.png'
subprocess.run([str(root/'build/creation-ascii'),'--time','3','--snapshot',str(path)],check=True)
shimmer=np.asarray(Image.open(path))
assert np.count_nonzero(first!=shimmer)>10000, 'Shimmer is not animated'
# Only the eyes are stable: head/beak retain their original animated characters.
for eye in [(slice(411,428),slice(922,935)),(slice(411,428),slice(970,983))]:
    assert np.array_equal(first[eye],shimmer[eye]), 'Stationary eye still shimmers'
assert not np.array_equal(first[355:395,890:1020],shimmer[355:395,890:1020]), 'Head shimmer was removed'
assert not np.array_equal(first[447:478,920:1000],shimmer[447:478,920:1000]), 'Beak shimmer was removed'
assert not np.array_equal(first[510:720,820:1110],shimmer[510:720,820:1110]), 'Body shimmer was removed'
print('PASS: stable eyes, body shimmer, static sides, animated center, visible edge-on thickness, symbol/color shimmer, opaque output')
