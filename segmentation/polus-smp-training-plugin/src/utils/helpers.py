import logging
import os
from pathlib import Path
from typing import Dict
from typing import Generator
from typing import List
from typing import Tuple
from tqdm import tqdm

import torch
import numpy
from bfio import BioReader
from filepattern import FilePattern

__all__ = [
    'POLUS_LOG',
    'TILE_STRIDE',
    'Tiles',
    'get_labels_mapping',
    'get_tiles_mapping',
    'get_device_memory',
]

POLUS_LOG = getattr(logging, os.environ.get('POLUS_LOG', 'INFO'))

TILE_STRIDE = 256

# List of 5-tuples of (file-path, x_min, x_max, y_min, y_max)
Tiles = List[Tuple[Path, int, int, int, int]]


def get_labels_mapping(images_fp: FilePattern, labels_fp: FilePattern) -> Dict[Path, Path]:
    """ Creates a filename map between images and labels
    In the case where image filenames have different filename 
    pattern than label filenames, this function creates a map
    between the corresponding images and labels
    
    Args:
        images_fp: filepattern object for images
        labels_fp: filepattern object for labels

    Returns:
        dictionary containing mapping between image & label names
    """
    # TODO: Get this working again
    # labels_map = {
    #     file[0]['file']: labels_fp.get_matching(**{
    #         k.upper(): v
    #         for k, v in file[0].items()
    #         if k != 'file'
    #     })[0]['file']
    #     for file in images_fp()
    # }
    # image_array = numpy.zeros((len(images_fp())))
    image_list = []
    label_list = []
    counter = 0
    for image, label in tqdm(zip(images_fp(), labels_fp())):
        
        image_file = image[0]['file']
        label_file = label[0]['file']
        assert os.path.basename(image_file) == os.path.basename(label_file)
        
        with BioReader(image[0]['file']) as br_image:
            br_image_shape = br_image.shape
            br_image = br_image[:].reshape(br_image_shape[:2])
            image_list.append(br_image)
        with BioReader(label[0]['file']) as br_label:
            br_label_shape = br_label.shape
            br_label = br_label[:].reshape(br_label_shape[:2])
            label_list.append(br_label)
            
        assert br_image_shape == br_label_shape
        
        counter += 1
        if counter > 63:
            break        

    image_array = numpy.stack(image_list, axis=0)
    label_array = numpy.stack(label_list, axis=0)

    # image_array = numpy.reshape(image_array, (1, shp[0], shp[1], shp[2]))
    # label_array = numpy.reshape(label_array, (1, shp[0], shp[1], shp[2]))
    # labels_map: Dict[Path, Path] = {
    #     image[0]['file']: label[0]['file']
    #     for image, label in zip(images_fp(), labels_fp())
    # }
    # for k, v in labels_map.items():
    #     assert k.name == v.name, f'image and label had different names: {k} vs {v}'
    return image_array, label_array


def iter_tiles_2d(image_path: Path) -> Generator[Tuple[Path, int, int, int, int], None, None]:
    with BioReader(image_path) as reader:
        y_end, x_end = reader.Y, reader.X

    for y_min in range(0, y_end, TILE_STRIDE):
        y_max = min(y_end, y_min + TILE_STRIDE)
        if (y_max - y_min) != TILE_STRIDE:
            continue

        for x_min in range(0, x_end, TILE_STRIDE):
            x_max = min(x_end, x_min + TILE_STRIDE)
            if (x_max - x_min) != TILE_STRIDE:
                continue

            yield image_path, y_min, y_max, x_min, x_max


def get_tiles_mapping(image_paths: List[Path]) -> Tiles:
    """ creates a tile map for the Dataset class
    This function iterates over all the files in the input 
    collection and creates a dictionary that can be used in 
    __getitem__ function in the Dataset class. 
    
    Args:
        image_paths: The paths to the images.
        
    Returns:
        All tile mappings
    """
    tiles: Tiles = list()

    for file_name in image_paths:
        tiles.extend(iter_tiles_2d(file_name))

    return tiles


def get_device_memory(device: torch.device) -> int:
    if 'cpu' in device.type:
        _, _, free_memory = map(int, os.popen('free -t -m').readlines()[-1].split()[1:])
        free_memory *= (1024 ** 2)
        # Use up to a quarter of RAM for CPU training
        free_memory = free_memory // 4
    else:
        total_memory = torch.cuda.get_device_properties(device).total_memory
        reserved_memory = torch.cuda.memory_reserved(device)
        free_memory = total_memory - reserved_memory

    return free_memory
