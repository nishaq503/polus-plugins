import logging
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple
from typing import Union

import albumentations
import numpy
import torch
import torch.nn
import torchvision
from albumentations.core.transforms_interface import BasicTransform
from bfio import BioReader
from torch import Tensor
from torch.utils.data import Dataset as TorchDataset

from . import helpers

__all__ = [
    'Dataset',
    'PoissonTransform',
    'LocalNorm',
]

logging.basicConfig(
    format='%(asctime)s - %(name)-8s - %(levelname)-8s - %(message)s',
    datefmt='%d-%b-%y %H:%M:%S',
)
logger = logging.getLogger("dataset")
logger.setLevel(helpers.POLUS_LOG)


class LocalNorm(object):
    def __init__(
            self,
            window_size: int = 129,
            max_response: Union[int, float] = 6,
    ):
        assert window_size % 2 == 1, 'window_size must be an odd integer'

        self.window_size: int = window_size
        self.max_response: float = float(max_response)
        self.pad = torchvision.transforms.Pad(window_size // 2 + 1, padding_mode='reflect')
        # Mode can be 'test', 'train' or 'eval'.
        self.mode: str = 'eval'

    def __call__(self, x: Tensor):
        return torch.clip(
            self.local_response(self.pad(x)),
            min=-self.max_response,
            max=self.max_response,
        )

    def image_filter(self, image: Tensor) -> Tensor:
        """ Use a box filter on a stack of images
        This method applies a box filter to an image. The input is assumed to be a
        4D array, and should be pre-padded. The output will be smaller by
        window_size - 1 pixels in both width and height since this filter does not pad
        the input to account for filtering.
        """
        integral_image: Tensor = image.cumsum(dim=-1).cumsum(dim=-2)
        return (
                integral_image[..., :-self.window_size - 1, :-self.window_size - 1]
                + integral_image[..., self.window_size:-1, self.window_size:-1]
                - integral_image[..., self.window_size:-1, :-self.window_size - 1]
                - integral_image[..., :-self.window_size - 1, self.window_size:-1]
        )

    def local_response(self, image: Tensor):
        """ Regional normalization.
        This method normalizes each pixel using the mean and standard deviation of
        all pixels within the window_size. The window_size parameter should be
        2 * radius + 1 of the desired region of pixels to normalize by. The image should
        be padded by window_size // 2 on each side.
        """
        local_mean: Tensor = self.image_filter(image) / (self.window_size ** 2)
        local_mean_square: Tensor = self.image_filter(image.pow(2)) / (self.window_size ** 2)

        # Use absolute difference because sometimes error causes negative values
        local_std = torch.clip(
            (local_mean_square - local_mean.pow(2)).abs().sqrt(),
            min=1e-3,
        )

        min_i, max_i = self.window_size // 2, -self.window_size // 2 - 1
        response = image[..., min_i:max_i, min_i:max_i]

        return (response - local_mean) / local_std


class GlobalNorm:
    # TODO
    pass


class PoissonTransform(BasicTransform):
    """ Apply poisson noise.
    Args:
        peak (int): [1-10] high values introduces more noise in the image
        p (float): probability of applying the transform. Default: 0.5.
    Targets:
        image
    Image types:
        float32 """

    def __init__(self, peak, always_apply=False, p=0.5):
        super(PoissonTransform, self).__init__(always_apply, p)
        self.peak = peak

    def apply(self, img, **params):
        value = numpy.exp(10 - self.peak)

        num_nans = numpy.sum(numpy.isnan(img))
        if num_nans > 0:
            message = f'image had {num_nans} nan values.'
            logger.error(message)
            raise ValueError(message)
        num_negatives = numpy.sum(img < 0)
        if num_negatives > 0:
            message = f'image had {num_negatives} negative values.'
            logger.error(message)
            raise ValueError(message)

        noisy_image = numpy.random.poisson(img * value).astype(numpy.float32) / value
        return noisy_image

    def update_params(self, params, **kwargs):
        if hasattr(self, "peak"):
            params["peak"] = self.peak
        return params

    @property
    def targets(self):
        return {"image": self.apply}

    def get_params_dependent_on_targets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def get_transform_init_args_names(self) -> Tuple[str, ...]:
        raise NotImplementedError


class Dataset(TorchDataset):
    def __init__(
            self,
            images: numpy.ndarray,
            labels: numpy.ndarray,
    ):

        self.images, self.labels = images, labels

    def __getitem__(self, index: int):

        image_tile = self.images[index].astype(numpy.float32)
        label_tile = self.labels[index].astype(numpy.float32)

        image_tile = image_tile[None, ...]
        label_tile = label_tile[None, ...]

        return image_tile, label_tile

    def __len__(self):
        return len(self.images)
