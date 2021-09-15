import abc
import logging
from concurrent.futures import Future
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Type

import filepattern
import numpy
from bfio import BioReader
from bfio import BioWriter
from sklearn import linear_model

import utils

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%d-%b-%y %H:%M:%S',
)
logger = logging.getLogger('models')
logger.setLevel(utils.POLUS_LOG)


class Model(abc.ABC):
    """ Base class for models that can be trained to estimate bleed-through. """

    __slots__ = (
        '__files',
        '__channel_overlap',
        '__coefficients',
        '__image_mins',
        '__image_maxs',
        '__kernel_size',
        '__num_pixels',
    )

    def __init__(
            self,
            files: list[Path],
            selected_tiles: utils.TileIndices,
            image_mins: list[int],
            image_maxs: list[int],
            channel_overlap: int,
            kernel_size: int,
    ):
        """ Trains a model on the given files.

        Args:
            files: Paths to images on which the model will be trained.
            selected_tiles: A list of indices of the tiles on which to train the model.
            image_mins: A list of the minimum brightnesses of all selected tiles for each channel.
            image_maxs: A list of the maximum brightnesses of all selected tiles for each channel.
            channel_overlap: The number of adjacent channels to consider for bleed-through estimation.
            kernel_size: The size of the convolutional kernel used to estimate bleed-through.
        """

        self.__files = files
        self.__image_mins = image_mins
        self.__image_maxs = image_maxs
        self.__channel_overlap = min(len(self.__files) - 1, max(1, channel_overlap))
        self.__kernel_size = kernel_size

        pad = 2 * (kernel_size // 2)
        self.__num_pixels = min(
            utils.MAX_DATA_SIZE // (4 * kernel_size ** 2 * self.__channel_overlap * 2),
            (utils.TILE_SIZE_2D - pad) ** 2,
        )

        self.__coefficients = self._fit(selected_tiles)

    @abc.abstractmethod
    def _init_model(self):
        """ Initialize a model. """
        pass

    @property
    def coefficients(self) -> numpy.ndarray:
        """ Returns the matrix of mixing coefficients from the trained model. """
        return self.__coefficients

    @property
    def image_mins(self) -> list[int]:
        return self.__image_mins

    @property
    def image_maxs(self) -> list[int]:
        return self.__image_maxs

    def _get_neighbors(self, source_index: int) -> list[int]:
        """ Get the neighboring channels for the given source-channel. """
        neighbor_indices = [source_index - i - 1 for i in range(self.__channel_overlap)]
        neighbor_indices.extend(source_index + i + 1 for i in range(self.__channel_overlap))
        neighbor_indices = list(filter(lambda i: 0 <= i < len(self.__files), neighbor_indices))
        return neighbor_indices

    def _fit_thread(self, source_index: int, selected_tiles: utils.TileIndices) -> list[float]:
        """ Trains a single model on a single source-channel and
         returns the mixing coefficients with the adjacent channels.

        This function can be run inside a thread in a ProcessPoolExecutor.

        Args:
            source_index: Index of the source channel.

        Returns:
            A list of the mixing coefficient with each neighboring channel
             within self.__channel_overlap of the source channel.
        """
        with BioReader(self.__files[source_index]) as source_reader:
            neighbor_readers = [
                BioReader(self.__files[i])
                for i in self._get_neighbors(source_index)
            ]

            mins = [self.image_mins[source_index]]
            mins.extend([self.image_mins[i] for i in self._get_neighbors(source_index)])
            maxs = [self.image_maxs[source_index]]
            maxs.extend([self.image_maxs[i] for i in self._get_neighbors(source_index)])

            logger.info(f'Fitting {self.__class__.__name__} {source_index} on {len(selected_tiles)} tiles...')
            model = self._init_model()
            for i, (z_min, z_max, y_min, y_max, x_min, x_max) in enumerate(selected_tiles):
                logger.info(
                    f'Fitting {self.__class__.__name__} {source_index}: '
                    f'Progress: {100 * i / len(selected_tiles):6.2f} %'
                )

                pad = self.__kernel_size // 2
                source_tile: numpy.ndarray = numpy.squeeze(
                    source_reader[
                        y_min + pad:y_max - pad,
                        x_min + pad:x_max - pad,
                        z_min + pad:z_max - pad,
                        0, 0
                    ]
                ).flatten()
                source_tile = utils.normalize_tile(source_tile, mins[0], maxs[0])

                num_pixels = (y_max - y_min - 2 * pad) * (x_max - x_min - 2 * pad)
                if num_pixels > self.__num_pixels:
                    indices = numpy.random.choice(num_pixels, size=(self.__num_pixels,), replace=False)
                else:
                    indices = numpy.arange(0, self.__num_pixels)

                tiles: list[numpy.ndarray] = [source_tile[indices]]

                for reader, min_val, max_val in zip(neighbor_readers, mins[1:], maxs[1:]):
                    tile = reader[y_min:y_max, x_min:x_max, z_min:z_max, 0, 0]
                    tile = utils.normalize_tile(tile, min_val, max_val)

                    for r in range(self.__kernel_size):
                        tile_y_min, tile_y_max = r, 1 + r - self.__kernel_size + tile.shape[0]

                        for c in range(self.__kernel_size):
                            tile_x_min, tile_x_max = c, 1 + c - self.__kernel_size + tile.shape[1]

                            cropped_tile = tile[tile_y_min:tile_y_max, tile_x_min:tile_x_max]
                            tiles.append(cropped_tile.flatten()[indices])

                tiles = numpy.asarray(tiles, dtype=numpy.float32).T

                source, neighbors = tiles[:, 0], tiles[:, 1:]
                interactions: numpy.ndarray = numpy.sqrt(numpy.expand_dims(source, axis=1) * neighbors)
                neighbors = numpy.concatenate([neighbors, interactions], axis=1)

                logger.info('start fit...')
                model.fit(neighbors, source)
                logger.info('end fit...')

            coefficients = list(map(float, model.coef_))
            del model
            [reader.close() for reader in neighbor_readers]

        return coefficients

    def _fit(self, selected_tiles: utils.TileIndices) -> numpy.ndarray:
        """ Fits the model on the images and returns a matrix of mixing coefficients. """

        # with ProcessPoolExecutor() as executor:
        #     coefficients_list: list[Future[list[float]]] = [
        #         executor.submit(self._fit_thread, source_index, selected_tiles)
        #         for source_index in range(len(self.__files))
        #     ]
        #     coefficients_list: list[list[float]] = [future.result() for future in coefficients_list]
        coefficients_list: list[list[float]] = [
            self._fit_thread(source_index, selected_tiles)
            for source_index in range(len(self.__files))
        ]

        # TODO: Fix the rest...
        coefficients_matrix = numpy.zeros(
            shape=(len(self.__files), 2 * len(self.__files)),
            dtype=numpy.float32,
        )
        for i, coefficients in enumerate(coefficients_list):
            # TODO: Can't use self._get_neighbors anymore
            neighbor_indices = self._get_neighbors(i)
            interaction_indices = [j + len(self.__files) for j in neighbor_indices]

            neighbor_indices = neighbor_indices + interaction_indices
            coefficients_matrix[i, neighbor_indices] = coefficients

        return coefficients_matrix

    def coefficients_to_csv(
            self,
            destination_dir: Path,
            pattern: str,
            group: list[utils.FPFileDict],
    ):
        """ Write the matrix of mixing coefficients to a csv.

        TODO: Learn how to use `filepattern` better and cut down on the input
         params. Ideally, we would only need the `destination_dir` as an input
         and the name for the csv would be generated from `self.__files`.

        Args:
            destination_dir: Directory were to write the csv.
            pattern: The pattern used for grouping images.
            group: The group of images for which the csv will be generated.
        """
        # noinspection PyTypeChecker
        name = filepattern.output_name(pattern, group, dict())

        metadata_path = destination_dir.joinpath(f'{name}_coefficients.csv')
        with open(metadata_path, 'w') as outfile:
            header_1 = ','.join(f'c{c}' for c in range(len(self.__files)))
            header_2 = ','.join(f'i{c}' for c in range(len(self.__files)))
            outfile.write(f'channel,{header_1},{header_2}\n')

            for channel, row in enumerate(self.coefficients):
                row = ','.join(f'{c:.6e}' for c in row)
                outfile.write(f'c{channel},{row}\n')

        return

    def write_components(self, destination_dir: Path):
        """ Write out the estimated bleed-through components.

        These bleed-through components can be subtracted from the original
        images to achieve bleed-through correction.

        Args:
            destination_dir: Path to the directory where the output images will
                              be written.
        """
        with ProcessPoolExecutor() as executor:
            processes = list()
            for source_index, input_path in enumerate(self.__files):
                writer_name = utils.replace_extension(input_path.name)
                processes.append(executor.submit(
                    self._write_components_thread,
                    destination_dir,
                    writer_name,
                    source_index,
                ))

            for process in processes:
                process.result()
        return

    def _write_components_thread(
            self,
            output_dir: Path,
            image_name: str,
            source_index: int,
    ):
        """ Writes the bleed-through components for a single image.

        This function can be run in a single thread in a ProcessPoolExecutor.

        Args:
            output_dir: Path for the directory of the bleed-through components.
            image_name: name of the source image.
            source_index: index of the source channel.
        """
        neighbor_indices = self._get_neighbors(source_index)

        readers = [BioReader(self.__files[i]) for i in neighbor_indices]
        coefficients = [float(c) for c in self.__coefficients[source_index, [neighbor_indices]][0]]
        neighbor_mins = [self.image_mins[i] for i in neighbor_indices]
        neighbor_maxs = [self.image_maxs[i] for i in neighbor_indices]

        with BioReader(self.__files[source_index]) as reader:
            metadata = reader.metadata
            num_tiles = utils.count_tiles_2d(reader)
            tile_indices = list(utils.tile_indices_2d(reader))

            with BioWriter(output_dir.joinpath(image_name), metadata=metadata) as writer:

                logger.info(f'Writing components for {image_name}...')
                for i, (z, y_min, y_max, x_min, x_max) in enumerate(tile_indices):
                    tile = numpy.squeeze(reader[y_min:y_max, x_min:x_max, z:z + 1, 0, 0])

                    original_component = numpy.zeros_like(tile)

                    if i % 10 == 0:
                        logger.info(f'Writing {image_name}: Progress {100 * i / num_tiles:6.2f} %')

                    for neighbor_reader, original_c, mins, maxs in zip(
                            readers, coefficients, neighbor_mins, neighbor_maxs
                    ):
                        neighbor_tile = numpy.squeeze(
                            neighbor_reader[y_min:y_max, x_min:x_max, z:z + 1, 0, 0]
                        ).astype(numpy.float32)
                        neighbor_tile = (neighbor_tile - mins) / (maxs - mins)

                        if original_c != 0:
                            # apply the coefficient
                            current_component = original_c * neighbor_tile
                            current_component[current_component < 0] = 0

                            # Rescale, but do not add in the minimum value offset.
                            current_component *= (maxs - mins)
                            original_component += current_component.astype(tile.dtype)

                    writer[y_min:y_max, x_min:x_max, z:z + 1, 0, 0] = original_component

        [reader.close() for reader in readers]
        return


class Lasso(Model):
    """ Uses sklearn.linear_model.Lasso

    This is the model used by the paper and source code (linked below) which we
     used as the seed for this plugin.

    https://doi.org/10.1038/s41467-021-21735-x
    https://github.com/RoysamLab/whole_brain_analysis
    """

    def _init_model(self):
        return linear_model.Lasso(alpha=1e-4, copy_X=True, positive=True, warm_start=True, max_iter=10)


class ElasticNet(Model):
    """ Uses sklearn.linear_model.ElasticNet """

    def _init_model(self):
        return linear_model.ElasticNet(alpha=1e-4, warm_start=True)


class PoissonGLM(Model):
    """ Uses sklearn.linear_model.PoissonRegressor """

    def _init_model(self):
        return linear_model.PoissonRegressor(alpha=1e-4, warm_start=True)


""" A dictionary to let us use a model by name. """
MODELS: dict[str, Type[Model]] = {
    'Lasso': Lasso,
    'PoissonGLM': PoissonGLM,
    'ElasticNet': ElasticNet,
}
