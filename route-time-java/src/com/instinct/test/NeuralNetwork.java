package com.instinct.test;


/*
 * A grid of 16,16 input layer neurons
 * 4*16*16 hidden layer neurons (layering is not trained)
 * 10 output neurons, encoding maximum of 1024 distinct items 
 */

public class NeuralNetwork {

	private int[] inputNeuronIds; //64 input neuron ids
	private int[] neuronIds; // 1024 ids of the hidden neurons.
	private int[] outputNeuronIds; //10 output neuron ids
	
	private Synapse[] synapses; //1024*1000 synapses

}

class Synapse {
	private int neuronIn; //65 to 1089
	private int neuronOut; //65 to 1089
}


