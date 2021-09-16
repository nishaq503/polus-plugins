#!/bin/bash

version=$(<VERSION)
data_path=$(readlink --canonicalize ../../data)

# Must be one of ERROR, CRITICAL, WARNING, INFO, DEBUG
POLUS_LOG=INFO

# Change to .ome.zarr to save output images as zarr files.
POLUS_EXT=".ome.tif"

# Inputs
<<<<<<< HEAD
<<<<<<< Updated upstream
<<<<<<< HEAD
inpDir=/data/images/MaricRatBrain2019/standard/intensity
filePattern="S1_R1_C1-C11_A1_c00{c}.ome.tif"
=======
inpDir=/data/input
filePattern="c{c}_mixed.ome.tif"
>>>>>>> d608bb9abb86e33032fc600fff5c964e6cbf03d7
=======
inpDir=/data/images/MaricRatBrain2019/standard/intensity
filePattern="S1_R1_C1-C11_A1_c0{cc}.ome.tif"
>>>>>>> Stashed changes
=======
inpDir=/data/input
filePattern="S1_R1_C1-C11_A1_y0(00-14)_x0(00-21)_c0{cc}.ome.tif"
>>>>>>> cb2ce954c0f6d8bbff48e857df63b04c142d5deb
groupBy="c"

# Output paths
outDir=/data/output

echo $[data_path]

docker run --mount type=bind,source=${data_path},target=/data/ \
            --user "$(id -u)":"$(id -g)" \
            --env POLUS_LOG=${POLUS_LOG} \
            --env POLUS_EXT=${POLUS_EXT} \
            polusai/bleed-through-estimation-plugin:"${version}" \
            --inpDir ${inpDir} \
            --filePattern ${filePattern} \
            --groupBy ${groupBy} \
            --outDir ${outDir}
