import warnings

import numpy as np
import matplotlib.pyplot as plt


def to_numpy(tensor, squeeze=True):
    """Converts a PyTorch Tensor to a NumPy array.

    :param tensor: A PyTorch tensor object (note this still works for Variables
        which are deprecated)
    :param squeeze: Whether to squeeze tensor (default: True)
    :return: PyTorch tensor as a NumPy array
    """
    if isinstance(tensor, np.ndarray):
        warnings.warn('to_numpy was passed tensor, but it is already a NumPy '
                      'ndarray. Continuing..')
        t_npy = tensor
    else:
        t_npy = tensor.cpu().detach().numpy()
    if squeeze:
        t_npy = np.squeeze(t_npy)
    return t_npy


def plot_sir_state(sir_state, title='SIR_state', show=True):
    # Plot the SIR state
    plt.plot(sir_state)
    legend_labels = ['I', 'R', 'S']
    if sir_state.shape[1] == 4:
        legend_labels.append('E')
    elif sir_state.shape[1] != 3:
        warnings.warn('plot_sir_state received `sir_state` with unexpected '
                      'shape {} (dim 1 not 3 or 4). Assuming SIR and using the '
                      'legend labels: {}'.format(sir_state.shape,
                                                 legend_labels))
    plt.legend(legend_labels)
    plt.xlabel('Day')
    plt.ylabel('Value')
    if title is not None:
        plt.title(title)
    if show:
        plt.show()
