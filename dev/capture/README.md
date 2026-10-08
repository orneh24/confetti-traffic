# README image capture

Regenerates `docs/img/dashboard-mock.jpg` and `docs/img/hub-pages.gif` from a
fresh Alpine hub container (real `chronyd`, so the header clock reads synced).
Run from the repo root. Needs Docker and Python with Playwright and Pillow.

```sh
sh dev/capture/capture_hub.sh seed_demo      # 5-node scene, one failing pair
python dev/capture/shot_dashboard.py         # -> docs/img/dashboard-mock.jpg
sh dev/capture/capture_hub.sh seed_tour      # 6-node, one-hour story + a mesh rule
python dev/capture/tour_gif.py 230 780       # -> docs/img/hub-pages.gif
docker rm -f ct-capture
```

- The capture hub is on host port 8199, so other lab containers on 8099 can't
  add nodes to the images.
- The container mounts the working tree, so uncommitted template edits show.
- `tour_gif.py` hardcodes captions, node names and element ids; check them
  when the UI changes. Temp PNGs go to `dev/run/` (gitignored).
- The `readme-image-capturer` agent runs all of this and checks the images.
