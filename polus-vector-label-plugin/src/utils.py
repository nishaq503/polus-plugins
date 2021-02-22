# Code sourced from https://github.com/MouseLand/cellpose/tree/master/cellpose
import numpy as np

def diameters(masks):
    """ get median 'diameter' of masks
    Args:
    masks(array): Labelled Image

    Returns:
    md(array): Median of the label
    counts(array[bool]): Boolean array containing occurrence of unique pixels.
    """
    _, counts = np.unique(np.int32(masks), return_counts=True)
    counts = counts[1:]
    md = np.median(counts**0.5)
    if np.isnan(md):
        md = 0
    md /= (np.pi**0.5)/2
    return md, counts**0.5