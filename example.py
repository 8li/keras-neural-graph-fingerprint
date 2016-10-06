from __future__ import division, print_function, absolute_import

from keras.layers import Input, merge, Dense
from keras import models

import utils
from preprocessing import tensorise_smiles
from NGF_layers import NeuralGraphHidden, NeuralGraphOutput

data, labels = utils.load_delaney()

# Parameters
conv_width = 8
fp_length = 62

# Tensorise data
X_atoms, X_bonds, X_edges = tensorise_smiles(data)
print(X_atoms.shape)
print(X_bonds.shape)
print(X_edges.shape)


# Load sizes from data shape
num_molecules = X_atoms.shape[0]
max_atoms = X_atoms.shape[1]
max_degree = X_bonds.shape[2]
num_atom_features = X_atoms.shape[-1]
num_bond_features = X_bonds.shape[-1]


# ============================== Build the Neural Graph Convnet. ==============================
# Define the input layers
atoms0 = Input(name='atom_inputs', shape=(max_atoms, num_atom_features))
bonds = Input(name='bond_inputs', shape=(max_atoms, max_degree, num_bond_features))
edges = Input(name='edge_inputs', shape=(max_atoms, max_degree), dtype='int32')

# Define the convoluted atom feature layers
atoms1 = NeuralGraphHidden(conv_width)([atoms0, bonds, edges])
atoms2 = NeuralGraphHidden(conv_width)([atoms1, bonds, edges])

# Define the outputs of each (convoluted) atom featuer layer to fingerprint
fp_out0 = NeuralGraphOutput(fp_length)([atoms0, bonds, edges])
fp_out1 = NeuralGraphOutput(fp_length)([atoms1, bonds, edges])
fp_out2 = NeuralGraphOutput(fp_length)([atoms2, bonds, edges])


# Sum outputs to obtain fingerprint
final_fp = merge([fp_out0, fp_out1, fp_out2], mode='sum')

# Build and compile model for regression.
main_prediction = Dense(1, activation='linear', name='main_prediction')(final_fp)
model = models.Model(input=[atoms0, bonds, edges], output=[main_prediction])
model.compile(optimizer='adagrad', loss='mse')

# Train the model
model.fit([X_atoms, X_bonds, X_edges], labels, nb_epoch=200, batch_size=10)