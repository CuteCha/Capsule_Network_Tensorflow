from config import args
import tensorflow as tf
from network_params import *
from tensorflow.examples.tutorials.mnist import input_data
import numpy as np


def load_mnist(mode='train'):
    """
    load the MNIST data
    :param mode: train or test
    :return: train and validation images and labels in train mode, test images and labels in test mode
            x: [#images, width, height, n_channels]
            y: [#images, 10] (one_hot_encoded)
    """
    mnist = input_data.read_data_sets("MNIST_data/", one_hot=True)
    if mode == 'train':
        x_train, y_train, x_valid, y_valid = mnist.train.images, mnist.train.labels, \
                                             mnist.validation.images, mnist.validation.labels
        x_train = x_train.reshape((-1, args.img_w, args.img_h, args.n_ch)).astype(np.float32)
        x_valid = x_valid.reshape((-1, args.img_w, args.img_h, args.n_ch)).astype(np.float32)
        return x_train, y_train, x_valid, y_valid
    elif mode == 'test':
        x_test, y_test = mnist.test.images, mnist.test.labels
        x_test = x_test.reshape((-1, args.img_w, args.img_h, args.n_ch)).astype(np.float32)
    return x_test, y_test


def load_fashion_mnist(mode='train'):
    pass


def load_data(dataset, mode='train'):
    if dataset == 'mnist':
        return load_mnist(mode)
    elif dataset == 'fashion-mnist':
        return load_fashion_mnist(mode)
    else:
        raise Exception('Invalid dataset, please check the name of dataset:', dataset)


def randomize(x, y):
    """ Randomizes the order of data samples and their corresponding labels"""
    permutation = np.random.permutation(y.shape[0])
    shuffled_x = x[permutation, :, :, :]
    shuffled_y = y[permutation]
    return shuffled_x, shuffled_y


def get_next_batch(x, y, start, end):
    x_batch = x[start:end]
    y_batch = y[start:end]
    return x_batch, y_batch


def squash(s, epsilon=1e-7, name=None):
    """
    Squashing function corresponding to Eq. 1
    :param s: A tensor with shape [batch_size, 1, num_caps, vec_len, 1] or [batch_size, num_caps, vec_len, 1].
    :param epsilon: To compute norm safely
    :param name:
    :return: A tensor with the same shape as vector but squashed in 'vec_len' dimension.
    """
    with tf.name_scope(name, default_name="squash"):
        squared_norm = tf.reduce_sum(tf.square(s), axis=-1, keep_dims=True)
        safe_norm = tf.sqrt(squared_norm + epsilon)
        squash_factor = squared_norm / (1. + squared_norm)
        unit_vector = s / safe_norm
        return squash_factor * unit_vector


def routing(inputs, b_ij, out_caps_dim):
    """
    The routing algorithm
    :param inputs: A tensor with [batch_size, num_caps_in=1152, 1, in_caps_dim=8, 1] shape.
                  num_caps_in: the number of capsule in layer l (i.e. PrimaryCaps).
                  in_caps_dim: dimension of the output vectors of layer l (i.e. PrimaryCaps)
    :param b_ij: [batch_size, num_caps_in=1152, num_caps_out=10, 1, 1]
                num_caps_out: the number of capsule in layer l+1 (i.e. DigitCaps).
    :param out_caps_dim: dimension of the output vectors of layer l+1 (i.e. DigitCaps)

    :return: A Tensor of shape [batch_size, num_caps_out=10, out_caps_dim=16, 1]
            representing the vector output `v_j` in layer l+1.
    """
    # W: [num_caps_in, num_caps_out, len_u_i, len_v_j]
    W = tf.get_variable('W', shape=(1, inputs.shape[1].value, b_ij.shape[2].value, inputs.shape[3].value, out_caps_dim),
                        dtype=tf.float32, initializer=tf.random_normal_initializer(stddev=args.stddev))

    inputs = tf.tile(inputs, [1, 1, b_ij.shape[2].value, 1, 1])
    # input => [batch_size, 1152, 10, 8, 1]

    W = tf.tile(W, [args.batch_size, 1, 1, 1, 1])
    # W => [batch_size, 1152, 10, 8, 16]

    u_hat = tf.matmul(W, inputs, transpose_a=True)
    # [batch_size, 1152, 10, 16, 1]

    # In forward, u_hat_stopped = u_hat; in backward, no gradient passed back from u_hat_stopped to u_hat
    u_hat_stopped = tf.stop_gradient(u_hat, name='stop_gradient')

    # For r iterations do
    for r_iter in range(args.iter_routing):
        with tf.variable_scope('iter_' + str(r_iter)):
            c_ij = tf.nn.softmax(b_ij, dim=2)
            # [batch_size, 1152, 10, 1, 1]

            # At last iteration, use `u_hat` in order to receive gradients from the following graph
            if r_iter == args.iter_routing - 1:
                s_j = tf.multiply(c_ij, u_hat)
                # [batch_size, 1152, 10, 16, 1]
                # then sum in the second dim
                s_j = tf.reduce_sum(s_j, axis=1, keep_dims=True)
                # [batch_size, 1, 10, 16, 1]
                v_j = squash(s_j)
                # [batch_size, 1, 10, 16, 1]

            elif r_iter < args.iter_routing - 1:  # Inner iterations, do not apply backpropagation
                s_j = tf.multiply(c_ij, u_hat_stopped)
                s_j = tf.reduce_sum(s_j, axis=1, keep_dims=True)
                v_j = squash(s_j)
                v_j_tiled = tf.tile(v_j, [1, inputs.shape[1].value, 1, 1, 1])
                # [batch_size, 1152, 10, 16, 1]

                # then matmul in the last two dim: [16, 1].T x [16, 1] => [1, 1]
                u_produce_v = tf.matmul(u_hat_stopped, v_j_tiled, transpose_a=True)
                # [batch_size, 1152, 10, 1, 1]

                b_ij += u_produce_v
    return tf.squeeze(v_j, axis=1)
    # [batch_size, 10, 16, 1]
