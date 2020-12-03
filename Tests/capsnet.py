#!/usr/bin/python

from __future__ import division, print_function, unicode_literals

import numpy as np
import tensorflow as tf
import TensorFI as ti

# seed value
tf.reset_default_graph()
tf.set_random_seed(42)
np.random.seed(42)

from tensorflow.examples.tutorials.mnist import input_data
mnist = input_data.read_data_sets("/tmp/data/")


X = tf.placeholder(shape=[None, 28, 28, 1], dtype=tf.float32, name="X")

#primary capsules
caps1_n_maps = 32
caps1_n_caps = caps1_n_maps * 6 * 6  # 1152 primary capsules
caps1_n_dims = 8

conv1 = tf.layers.conv2d(
            inputs = X ,
            filters = 256,
            kernel_size = 9,
            strides = 1,
            padding = 'valid',
            activation = tf.nn.relu
        )

conv2 = tf.layers.conv2d(
            inputs = conv1 ,
            filters = caps1_n_maps * caps1_n_dims,
            kernel_size = 9,
            strides = 2,
            padding = 'valid',
            activation = tf.nn.relu
        )

caps1_raw = tf.reshape(conv2, [-1, caps1_n_caps, caps1_n_dims],name="caps1_raw")
                   
def squash(s, axis=-1, epsilon=1e-7, name=None):
    with tf.name_scope(name, default_name="squash"):
        squared_norm = tf.reduce_sum(tf.square(s), axis=axis,
                                     keepdims=True)
        safe_norm = tf.sqrt(squared_norm + epsilon)
        squash_factor = squared_norm / (1. + squared_norm)
        unit_vector = s / safe_norm
        return squash_factor * unit_vector

caps1_output = squash(caps1_raw, name="caps1_output")

#digit capsules
caps2_n_caps = 10
caps2_n_dims = 16
init_sigma = 0.1

W_init = tf.random_normal(
    shape=(1, caps1_n_caps, caps2_n_caps, caps2_n_dims, caps1_n_dims),
    stddev=init_sigma, dtype=tf.float32, name="W_init")
W = tf.Variable(W_init, name="W")

batch_size = tf.shape(X)[0]
W_tiled = tf.tile(W, [batch_size, 1, 1, 1, 1], name="W_tiled")

caps1_output_expanded = tf.expand_dims(caps1_output, -1,
                                       name="caps1_output_expanded")
caps1_output_tile = tf.expand_dims(caps1_output_expanded, 2,
                                   name="caps1_output_tile")
caps1_output_tiled = tf.tile(caps1_output_tile, [1, 1, caps2_n_caps, 1, 1],
                             name="caps1_output_tiled")

caps2_predicted = tf.matmul(W_tiled, caps1_output_tiled,
                            name="caps2_predicted")

#Routing by agreement
raw_weights = tf.zeros([batch_size, caps1_n_caps, caps2_n_caps, 1, 1],
                       dtype=np.float32, name="raw_weights")

routing_weights = tf.nn.softmax(raw_weights, axis=2, name="routing_weights")

weighted_predictions = tf.multiply(routing_weights, caps2_predicted,
                                   name="weighted_predictions")
weighted_sum = tf.reduce_sum(weighted_predictions, axis=1, keepdims=True,
                             name="weighted_sum")
caps2_output_round_1 = squash(weighted_sum, axis=-2,
                              name="caps2_output_round_1")        

caps2_output_round_1_tiled = tf.tile(
    caps2_output_round_1, [1, caps1_n_caps, 1, 1, 1],
    name="caps2_output_round_1_tiled")

agreement = tf.matmul(caps2_predicted, caps2_output_round_1_tiled,
                      transpose_a=True, name="agreement")

raw_weights_round_2 = tf.add(raw_weights, agreement,
                             name="raw_weights_round_2")

routing_weights_round_2 = tf.nn.softmax(raw_weights_round_2,
                                        axis=2,
                                        name="routing_weights_round_2")
weighted_predictions_round_2 = tf.multiply(routing_weights_round_2,
                                           caps2_predicted,
                                           name="weighted_predictions_round_2")
weighted_sum_round_2 = tf.reduce_sum(weighted_predictions_round_2,
                                     axis=1, keepdims=True,
                                     name="weighted_sum_round_2")
caps2_output_round_2 = squash(weighted_sum_round_2,
                              axis=-2,
                              name="caps2_output_round_2")

caps2_output = caps2_output_round_2

def safe_norm(s, axis=-1, epsilon=1e-7, keepdims=False, name=None):
    with tf.name_scope(name, default_name="safe_norm"):
        squared_norm = tf.reduce_sum(tf.square(s), axis=axis,
                                     keepdims=keepdims)
        return tf.sqrt(squared_norm + epsilon)

y_proba = safe_norm(caps2_output, axis=-2, name="y_proba")

y_proba_argmax = tf.argmax(y_proba, axis=2, name="y_proba")

y_pred = tf.squeeze(y_proba_argmax, axis=[1,2], name="y_pred")

y = tf.placeholder(shape=[None], dtype=tf.int64, name="y")

m_plus = 0.9
m_minus = 0.1
lambda_ = 0.5

T = tf.one_hot(y, depth=caps2_n_caps, name="T")

caps2_output_norm = safe_norm(caps2_output, axis=-2, keepdims=True,
                              name="caps2_output_norm")

present_error_raw = tf.square(tf.maximum(0., m_plus - caps2_output_norm),
                              name="present_error_raw")
present_error = tf.reshape(present_error_raw, shape=(-1, 10),
                           name="present_error")

absent_error_raw = tf.square(tf.maximum(0., caps2_output_norm - m_minus),
                             name="absent_error_raw")
absent_error = tf.reshape(absent_error_raw, shape=(-1, 10),
                          name="absent_error")

L = tf.add(T * present_error, lambda_ * (1.0 - T) * absent_error,
           name="L")

margin_loss = tf.reduce_mean(tf.reduce_sum(L, axis=1), name="margin_loss")

n_hidden1 = 512
n_hidden2 = 1024
n_output = 28 * 28

mask_with_labels = tf.placeholder_with_default(False, shape=(),
                                               name="mask_with_labels")
reconstruction_targets = tf.cond(mask_with_labels, # condition
                                 lambda: y,        # if True
                                 lambda: y_pred,   # if False
                                 name="reconstruction_targets")
reconstruction_mask = tf.one_hot(reconstruction_targets,
                                 depth=caps2_n_caps,
                                 name="reconstruction_mask")

reconstruction_mask_reshaped = tf.reshape(
    reconstruction_mask, [-1, 1, caps2_n_caps, 1, 1],
    name="reconstruction_mask_reshaped")

caps2_output_masked = tf.multiply(
    caps2_output, reconstruction_mask_reshaped,
    name="caps2_output_masked")

decoder_input = tf.reshape(caps2_output_masked,
                           [-1, caps2_n_caps * caps2_n_dims],
                           name="decoder_input")

with tf.name_scope("decoder"):
    hidden1 = tf.layers.dense(decoder_input, n_hidden1,
                              activation=tf.nn.relu,
                              name="hidden1")
    hidden2 = tf.layers.dense(hidden1, n_hidden2,
                              activation=tf.nn.relu,
                              name="hidden2")
    decoder_output = tf.layers.dense(hidden2, n_output,
                                     activation=tf.nn.sigmoid,
                                     name="decoder_output")

X_flat = tf.reshape(X, [-1, n_output], name="X_flat")
squared_difference = tf.square(X_flat - decoder_output,
                               name="squared_difference")
reconstruction_loss = tf.reduce_mean(squared_difference,
                                    name="reconstruction_loss")

alpha = 0.0005

loss = tf.add(margin_loss, alpha * reconstruction_loss, name="loss")

correct = tf.equal(y, y_pred, name="correct")
accuracy = tf.reduce_mean(tf.cast(correct, tf.float32), name="accuracy")

optimizer = tf.train.AdamOptimizer()
training_op = optimizer.minimize(loss, name="training_op")


init = tf.global_variables_initializer()
#saver = tf.train.Saver()



n_epochs = 1
batch_size = 50
#restore_checkpoint = True
n_iterations_per_epoch =100
n_iterations_validation = 50
#n_iterations_per_epoch = mnist.train.num_examples // batch_size
#n_iterations_validation = mnist.validation.num_examples // batch_size
best_loss_val = np.infty

#checkpoint_path = "/local-scratch/hamidmousavi/mahdisajedi/TensorFI/Tests/DNN-model/CapsNet/checkpoint/"


with tf.Session() as sess:
 #   if restore_checkpoint and tf.train.checkpoint_exists(checkpoint_path):
  #     saver.restore(sess, checkpoint_path)
   # else:
    sess.run(init)

    for epoch in range(n_epochs):
        for iteration in range(1, n_iterations_per_epoch + 1):
            X_batch, y_batch = mnist.train.next_batch(batch_size)
            # Run the training operation and measure the loss:
            _, loss_train = sess.run(
                [training_op, loss],
                feed_dict={X: X_batch.reshape([-1, 28, 28, 1]),
                           y: y_batch,
                           mask_with_labels: True})
            print("\rIteration: {}/{} ({:.1f}%)  Loss: {:.5f}".format(
                      iteration, n_iterations_per_epoch,
                      iteration * 100 / n_iterations_per_epoch,
                      loss_train),
                  end="")

        # At the end of each epoch,
        # measure the validation loss and accuracy:
        loss_vals = []
        acc_vals = []
        for iteration in range(1, n_iterations_validation + 1):
            X_batch, y_batch = mnist.validation.next_batch(batch_size)
            loss_val, acc_val = sess.run(
                    [loss, accuracy],
                    feed_dict={X: X_batch.reshape([-1, 28, 28, 1]),
                               y: y_batch})
            loss_vals.append(loss_val)
            acc_vals.append(acc_val)
            print("\rEvaluating the model: {}/{} ({:.1f}%)".format(
                      iteration, n_iterations_validation,
                      iteration * 100 / n_iterations_validation),
                  end=" " * 10)
        loss_val = np.mean(loss_vals)
        acc_val = np.mean(acc_vals)
        print("\rEpoch: {}  Val accuracy: {:.4f}%  Loss: {:.6f}{}".format(
            epoch + 1, acc_val * 100, loss_val,
            " (improved)" if loss_val < best_loss_val else ""))

        # And save the model if it improved:
        #if loss_val < best_loss_val:
         #  save_path = saver.save(sess, checkpoint_path)
          # best_loss_val = loss_val

#n_iterations_test = mnist.test.num_examples // batch_size

#with tf.Session() as sess:
    #saver.restore(sess, checkpoint_path)

    #loss_tests = []
    acc_tests = []
    for iteration in range(5):
        X_batch, y_batch = mnist.test.next_batch(batch_size)
        xx=X_batch.reshape([-1, 28, 28, 1])
       
        acc_test = sess.run(accuracy,feed_dict={X: xx , y: y_batch})
      #  loss_tests.append(loss_test)
        acc_tests.append(acc_test)
      #  print("\rEvaluating the model: {}/{} ({:.1f}%)".format(
       #           iteration, n_iterations_test,
        #          iteration * 100 / n_iterations_test),
         #     end=" " * 10)
    #loss_test = np.mean(loss_tests)
    fi = ti.TensorFI(sess, logLevel = 10, disableInjections = False)
    acc = np.mean(acc_tests)
    #print("\rFinal test accuracy: {:.4f}%  Loss: {:.6f}".format(
     #   acc_test * 100, loss_test))
    # Add the fault injection code here to instrument the graph
    #fi = ti.TensorFI(sess, logLevel = 10, disableInjections = True)
    #print("Accuracy (with injections):", \
        #      accuracy.eval({X: X_batch.reshape([-1, 28, 28, 1]), y: y_batch}))
    #acc_test = sess.run(accuracy,feed_dict={X: X_batch.reshape([-1, 28, 28, 1]), y: y_batch})

    print("Testing Accuracy:", acc)