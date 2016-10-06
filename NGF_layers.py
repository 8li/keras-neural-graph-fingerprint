from __future__ import print_function

import numpy as np

from keras import layers
import keras.backend as K

import theano

# TODO: Rewrite this function to Keras and drop theano dependency
def parallel_gather(references, indices):
    ''' 
    Executes theano index (i.e. K.gather()) for each sample in a batch, usefull 
    when dealing with Tensor of dim > 2D
    '''
    result, _ = theano.scan(fn=lambda reference, indices:reference[indices],
        outputs_info=None, sequences=[references, indices])
    return result

class NeuralGraphHidden(layers.Layer):
    ''' Hidden Convolutional layer in a Neural Graph (as in Duvenaud et. al.,
    2015). This layer takes a graph as an input. The graph is represented as by 
    three tensors. 

    - The atoms tensor represents the features of the nodes. 
    - The bonds tensor represents the features of the edges.
    - The edges tensor represents the connectivity (which atoms are connected to
        which)

    It returns the convolved features tensor, which is very similar to the atoms
    tensor. Instead of each node being represented by a num_atom_features-sized
    vector, each node now is represented by a convolved feature vector of size 
    conv_width.

    # Arguments
        conv_width: The width of the convolution. This determines the size of 
            the feature vectors that are returned for each atom.

    # Input shape
        List of Atom and edge tensors of shape:
        `[(samples, max_atoms, atom_features), (samples, max_atoms, max_degrees,
          bond_features), (samples, max_atoms, max_degrees)]`
        where degrees referes to number of neighbours

    # Output shape
        New atom featuers of shape
        `(samples, max_atoms, conv_width)`

    # References
        - [Convolutional Networks on Graphs for Learning Molecular Fingerprints](https://arxiv.org/abs/1509.09292)

    # TODO
        - Add options for dense layer
        - Add naming for internal layers
    '''

    def __init__(self, conv_width, **kwargs):
        self.conv_width = conv_width
        super(NeuralGraphHidden, self).__init__(**kwargs)

    def build(self, inputs_shape):

        # Import dimensions
        atoms_shape, bonds_shape, edges_shape = inputs_shape
        max_atoms = atoms_shape[1]
        num_features = atoms_shape[2]
        max_degree = edges_shape[2]

        self.max_degree = max_degree

        # Add the dense layers (that contain trainable params)
        # (or each degree we convolve with a different weight matrix)
        self.dense_layers = [layers.Dense(self.conv_width) for _ in range(max_degree)]
        #TODO: Build dense_layers here in NGF build function
        #TODO: Investigate trainable params

    def call(self, inputs, mask=None):
        atoms, bonds, edges = inputs

        # Import dimensions
        num_samples = atoms._keras_shape[0]
        max_atoms = atoms._keras_shape[1]
        atom_features = atoms._keras_shape[-1]
        bond_features = bonds._keras_shape[-1]

        # Create a matrix that stores for each atom, the degree it is
        atom_degrees = K.sum(K.not_equal(edges, -1), axis=-1, keepdims=True)

        # The lookup masking trick: We add 1 to all indices, converting the 
        #   masking value of -1 to a valid 0 index.
        masked_edges = edges + 1
        # We then add a zerovector to the left of the lookup matrix, 
        # note: this keras adds a zero vector to the left AND right, but that is 
        #   okay for now
        masked_atom_features_lookup = K.temporal_padding(atoms, padding=1)

        # For each atom, look up the featues of it's neighbour
        neighbour_atom_features = parallel_gather(masked_atom_features_lookup, masked_edges)

        # Sum along degree axis to get summed neighbour features, also add the self
        summed_atom_features = K.sum(neighbour_atom_features, axis=-2) + atoms

        # Sum the edge features for each atom
        summed_bond_features = K.sum(bonds, axis=-2)

        # Concatenate the summed atom and bond features
        summed_features = K.concatenate([summed_atom_features, summed_bond_features], axis=-1)
        
        # For each degree we convolve with a different weight matrix
        new_features_by_degree = []
        for degree in range(self.max_degree):

            # Create mask for this degree
            atom_masks_this_degree = K.equal(atom_degrees, degree)

            # Multiply with hidden merge layer
            #   (use time Distributed because we are dealing with 2D input/3D for batches)
            # Add keras shape to let keras now the dimensions
            summed_features._keras_shape = (num_samples, max_atoms, atom_features+bond_features)
            new_unmasked_features = layers.TimeDistributed(self.dense_layers[degree])(summed_features)

            # Do explicit masking because TimeDistributed does not support masking
            new_masked_features = new_unmasked_features * atom_masks_this_degree

            new_features_by_degree.append(new_masked_features)

        # Finally sum the features of all atoms
        new_features = layers.merge(new_features_by_degree, mode='sum')

        return new_features

    def get_output_shape_for(self, inputs_shape):

        # Import dimensions
        atoms_shape, bonds_shape, edges_shape = inputs_shape
        num_samples = atoms_shape[0]
        max_atoms = atoms_shape[1]
        num_features = atoms_shape[2]
        max_degree = edges_shape[2]

        return (num_samples, max_atoms, self.conv_width)


class NeuralGraphOutput(layers.Layer):
    ''' Output Convolutional layer in a Neural Graph (as in Duvenaud et. al.,
    2015). This layer takes a graph as an input. The graph is represented as by 
    three tensors. 

    - The atoms tensor represents the features of the nodes. 
    - The bonds tensor represents the features of the edges.
    - The edges tensor represents the connectivity (which atoms are connected to
        which)

    It returns the fingerprint vector for each sample for the given layer.

    According to the original paper, the fingerprint outputs of each hidden layer
    need to be summed in the end to come up with the final fingerprint.    

    # Arguments
        fp_length: The length of the fingerprints returned.

    # Input shape
        List of Atom and edge tensors of shape:
        `[(samples, max_atoms, atom_features), (samples, max_atoms, max_degrees,
          bond_features), (samples, max_atoms, max_degrees)]`
        where degrees referes to number of neighbours

    # Output shape
        Fingerprints matrix
        `(samples, fp_length)`

    # References
        - [Convolutional Networks on Graphs for Learning Molecular Fingerprints](https://arxiv.org/abs/1509.09292)

    # TODO
        - Add options for dense layer
        - Add naming for internal layers            
    '''

    def __init__(self, fp_length, **kwargs):
        self.fp_length = fp_length
        super(NeuralGraphOutput, self).__init__(**kwargs)

    def build(self, inputs_shape):

        # Import dimensions
        atoms_shape, bonds_shape, edges_shape = inputs_shape
        max_atoms = atoms_shape[1]
        num_features = atoms_shape[2]
        max_degree = edges_shape[2]

        # Add the dense layer that contains the trainable parameters
        self.dense_layer = layers.Dense(self.fp_length)
        #TODO: Build dense_layer here in NGF build function


    def call(self, inputs, mask=None):
        atoms, bonds, edges = inputs

        # Create a matrix that stores for each atom, the degree it is, use it 
        #   to create a general atom mask (unused atoms are 0 padded)
        # We have to use the edge vector for this, because in theory, a convolution
        #   could lead to a zero vector for an atom that is present in the molecule
        atom_degrees = K.sum(K.not_equal(edges, -1), axis=-1, keepdims=True)
        general_atom_mask = K.not_equal(atom_degrees, 0)

        # Compute fingerprint
        fingerprint_out_unmasked = layers.TimeDistributed(self.dense_layer)(atoms)

        # Do explicit masking because TimeDistributed does not support masking
        fingerprint_out_masked = fingerprint_out_unmasked * general_atom_mask

        # Sum across all atoms
        final_fp_out = K.sum(fingerprint_out_masked, axis=-2)

        return final_fp_out

    def get_output_shape_for(self, inputs_shape):

        # Import dimensions
        atoms_shape, bonds_shape, edges_shape = inputs_shape
        num_samples = atoms_shape[0]
        max_atoms = atoms_shape[1]
        num_features = atoms_shape[2]
        max_degree = edges_shape[2]

        return (num_samples, self.fp_length)