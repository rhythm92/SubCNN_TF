# --------------------------------------------------------
# Fast R-CNN
# Copyright (c) 2015 Microsoft
# Licensed under The MIT License [see LICENSE for details]
# Written by Ross Girshick
# --------------------------------------------------------

"""Train a Fast R-CNN network."""

import caffe
from fast_rcnn.config import cfg
import gt_data_layer.roidb as gdl_roidb
import roi_data_layer.roidb as rdl_roidb
from utils.timer import Timer
import numpy as np
import os
import tensorflow as tf

from caffe.proto import caffe_pb2
import google.protobuf as pb2

class SolverWrapper(object):
    """A simple wrapper around Caffe's solver.
    This wrapper gives us control over he snapshotting process, which we
    use to unnormalize the learned bounding-box regression weights.
    """

    def __init__(self, sess, network, roidb, output_dir, pretrained_model=None):
        """Initialize the SolverWrapper."""
        self.net = network
        self.roidb = roidb
        self.output_dir = output_dir

        print 'Computing bounding-box regression targets...'
        if cfg.TRAIN.BBOX_REG:
            if cfg.IS_RPN:
                self.bbox_means, self.bbox_stds = gdl_roidb.add_bbox_regression_targets(roidb)
            else:
                self.bbox_means, self.bbox_stds = rdl_roidb.add_bbox_regression_targets(roidb)
        print 'done'

        if pretrained_model is not None:
            print ('Loading pretrained model '
                   'weights from {:s}').format(pretrained_model)
            self.net.load(pretrained_model, sess)
        else:
            sess.run(tf.initialize_all_variables())


    def snapshot(self):
        """Take a snapshot of the network after unnormalizing the learned
        bounding-box regression weights. This enables easy use at test-time.
        """
        net = self.solver.net

        if cfg.TRAIN.BBOX_REG and net.params.has_key('bbox_pred'):
            # save original values
            orig_0 = net.params['bbox_pred'][0].data.copy()
            orig_1 = net.params['bbox_pred'][1].data.copy()

            # scale and shift with bbox reg unnormalization; then save snapshot
            net.params['bbox_pred'][0].data[...] = \
                    (net.params['bbox_pred'][0].data *
                     self.bbox_stds[:, np.newaxis])
            net.params['bbox_pred'][1].data[...] = \
                    (net.params['bbox_pred'][1].data *
                     self.bbox_stds + self.bbox_means)

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        infix = ('_' + cfg.TRAIN.SNAPSHOT_INFIX
                 if cfg.TRAIN.SNAPSHOT_INFIX != '' else '')
        filename = (self.solver_param.snapshot_prefix + infix +
                    '_iter_{:d}'.format(self.solver.iter) + '.caffemodel')
        filename = os.path.join(self.output_dir, filename)

        net.save(str(filename))
        print 'Wrote snapshot to: {:s}'.format(filename)

        if cfg.TRAIN.BBOX_REG and net.params.has_key('bbox_pred'):
            # restore net to original state
            net.params['bbox_pred'][0].data[...] = orig_0
            net.params['bbox_pred'][1].data[...] = orig_1

    def train_model(self, sess, max_iters):
        """Network training loop."""

        data_layer = get_data_layer(self.roidb)

        last_snapshot_iter = -1
        timer = Timer()
        for i in range(max_iters):
            # get one batch
            blobs = data_layer.forward()
            # Make one SGD update
            timer.tic()
            self.solver.step(1)
            timer.toc()
            if self.solver.iter % (10 * self.solver_param.display) == 0:
                print 'speed: {:.3f}s / iter'.format(timer.average_time)

            if self.solver.iter % cfg.TRAIN.SNAPSHOT_ITERS == 0:
                last_snapshot_iter = self.solver.iter
                self.snapshot()

        if last_snapshot_iter != self.solver.iter:
            self.snapshot()

def get_training_roidb(imdb):
    """Returns a roidb (Region of Interest database) for use in training."""
    if cfg.TRAIN.USE_FLIPPED:
        print 'Appending horizontally-flipped training examples...'
        imdb.append_flipped_images()
        print 'done'

    print 'Preparing training data...'
    if cfg.IS_RPN:
        if cfg.IS_MULTISCALE:
            gdl_roidb.prepare_roidb(imdb)
        else:
            rdl_roidb.prepare_roidb(imdb)
    else:
        rdl_roidb.prepare_roidb(imdb)
    print 'done'

    return imdb.roidb


def get_data_layer(roidb):
    """return a data layer."""
    if cfg.IS_RPN:
        if cfg.IS_MULTISCALE:
            layer = GtDataLayer(roidb)
        else:
            layer = RoIDataLayer(roidb)
    else:
        layer = RoIDataLayer(roidb)

    return layer


def train_net(network, roidb, output_dir, pretrained_model=None, max_iters=40000):
    """Train a Fast R-CNN network."""

    with tf.Session() as sess:
        sw = SolverWrapper(sess, network, roidb, output_dir, pretrained_model=pretrained_model)

        print 'Solving...'
        sw.train_model(sess, max_iters)
        print 'done solving'
