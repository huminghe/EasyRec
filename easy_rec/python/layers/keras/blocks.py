# -*- encoding:utf-8 -*-
# Copyright (c) Alibaba, Inc. and its affiliates.
"""Convenience blocks for building models."""
import logging

import tensorflow as tf

from easy_rec.python.layers.keras.activation import activation_layer
from easy_rec.python.utils.tf_utils import add_elements_to_collection

if tf.__version__ >= '2.0':
  tf = tf.compat.v1


class MLP(tf.keras.layers.Layer):
  """Sequential multi-layer perceptron (MLP) block.

  Attributes:
    units: Sequential list of layer sizes.
    use_bias: Whether to include a bias term.
    activation: Type of activation to use on all except the last layer.
    final_activation: Type of activation to use on last layer.
    **kwargs: Extra args passed to the Keras Layer base class.
  """

  def __init__(self, params, name='mlp', reuse=None, **kwargs):
    super(MLP, self).__init__(name=name, **kwargs)
    params.check_required('hidden_units')
    use_bn = params.get_or_default('use_bn', True)
    use_final_bn = params.get_or_default('use_final_bn', True)
    use_bias = params.get_or_default('use_bias', False)
    use_final_bias = params.get_or_default('use_final_bias', False)
    dropout_rate = list(params.get_or_default('dropout_ratio', []))
    activation = params.get_or_default('activation', 'relu')
    initializer = params.get_or_default('initializer', 'he_uniform')
    final_activation = params.get_or_default('final_activation', None)
    use_bn_after_act = params.get_or_default('use_bn_after_activation', False)
    units = list(params.hidden_units)
    logging.info(
        'MLP(%s) units: %s, dropout: %r, activate=%s, use_bn=%r, final_bn=%r,'
        ' final_activate=%s, bias=%r, initializer=%s, bn_after_activation=%r' %
        (name, units, dropout_rate, activation, use_bn, use_final_bn,
         final_activation, use_bias, initializer, use_bn_after_act))
    assert len(units) > 0, 'MLP(%s) takes at least one hidden units' % name
    self.reuse = reuse

    num_dropout = len(dropout_rate)
    self._sub_layers = []
    for i, num_units in enumerate(units[:-1]):
      name = 'layer_%d' % i
      drop_rate = dropout_rate[i] if i < num_dropout else 0.0
      self.add_rich_layer(num_units, use_bn, drop_rate, activation, initializer,
                          use_bias, use_bn_after_act, name,
                          params.l2_regularizer)

    n = len(units) - 1
    drop_rate = dropout_rate[n] if num_dropout > n else 0.0
    name = 'layer_%d' % n
    self.add_rich_layer(units[-1], use_final_bn, drop_rate, final_activation,
                        initializer, use_final_bias, use_bn_after_act, name,
                        params.l2_regularizer)

  def add_rich_layer(self,
                     num_units,
                     use_bn,
                     dropout_rate,
                     activation,
                     initializer,
                     use_bias,
                     use_bn_after_activation,
                     name,
                     l2_reg=None):
    act_layer = activation_layer(activation)
    if use_bn and not use_bn_after_activation:
      dense = tf.keras.layers.Dense(
          units=num_units,
          use_bias=use_bias,
          kernel_initializer=initializer,
          kernel_regularizer=l2_reg,
          name=name)
      self._sub_layers.append(dense)
      bn = tf.keras.layers.BatchNormalization(
          name='%s/bn' % name, trainable=True)
      self._sub_layers.append(bn)
      self._sub_layers.append(act_layer)
    else:
      dense = tf.keras.layers.Dense(
          num_units,
          use_bias=use_bias,
          kernel_initializer=initializer,
          kernel_regularizer=l2_reg,
          name=name)
      self._sub_layers.append(dense)
      self._sub_layers.append(act_layer)
      if use_bn and use_bn_after_activation:
        bn = tf.keras.layers.BatchNormalization(name='%s/bn' % name)
        self._sub_layers.append(bn)

    if 0.0 < dropout_rate < 1.0:
      dropout = tf.keras.layers.Dropout(dropout_rate, name='%s/dropout' % name)
      self._sub_layers.append(dropout)
    elif dropout_rate >= 1.0:
      raise ValueError('invalid dropout_ratio: %.3f' % dropout_rate)

  def call(self, x, training=None, **kwargs):
    """Performs the forward computation of the block."""
    for layer in self._sub_layers:
      cls = layer.__class__.__name__
      if cls in ('Dropout', 'BatchNormalization', 'Dice'):
        x = layer(x, training=training)
        if cls in ('BatchNormalization', 'Dice'):
          add_elements_to_collection(layer.updates, tf.GraphKeys.UPDATE_OPS)
      else:
        x = layer(x)
    return x


class Highway(tf.keras.layers.Layer):

  def __init__(self, params, name='highway', reuse=None, **kwargs):
    super(Highway, self).__init__(name, **kwargs)
    self.emb_size = params.get_or_default('emb_size', None)
    self.num_layers = params.get_or_default('num_layers', 1)
    self.activation = params.get_or_default('activation', 'gelu')
    self.dropout_rate = params.get_or_default('dropout_rate', 0.0)
    self.init_gate_bias = params.get_or_default('init_gate_bias', -3.0)
    self.reuse = reuse

  def call(self, inputs, training=None, **kwargs):
    from easy_rec.python.layers.common_layers import highway
    return highway(
        inputs,
        self.emb_size,
        activation=self.activation,
        num_layers=self.num_layers,
        dropout=self.dropout_rate if training else 0.0,
        init_gate_bias=self.init_gate_bias,
        scope=self.name,
        reuse=self.reuse)


class Gate(tf.keras.layers.Layer):
  """Weighted sum gate."""

  def __init__(self, params, name='gate', reuse=None, **kwargs):
    super(Gate, self).__init__(name, **kwargs)
    self.weight_index = params.get_or_default('weight_index', 0)

  def call(self, inputs, **kwargs):
    assert len(
        inputs
    ) > 1, 'input of Gate layer must be a list containing at least 2 elements'
    weights = inputs[self.weight_index]
    j = 0
    for i, x in enumerate(inputs):
      if i == self.weight_index:
        continue
      if j == 0:
        output = weights[:, j, None] * x
      else:
        output += weights[:, j, None] * x
      j += 1
    return output
