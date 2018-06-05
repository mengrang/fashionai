# -*- coding: utf-8 -*-
import tensorflow as tf
import numpy as np
import cv2
import os
import importlib
import time
import configparser
from config import FLAGS
from preprocess.datagenerator import DataGenerator


def process_config(conf_file):
    params = {}
    config = configparser.ConfigParser()
    config.read(conf_file)
    for section in config.sections():
        if section == 'DataSetHG':
            for option in config.options(section):
                params[option] = eval(config.get(section, option))
        if section == 'blouse':
            for option in config.options(section):
                params[option] = eval(config.get(section, option))
        if section == 'dress':
            for option in config.options(section):
                params[option] = eval(config.get(section, option))
        if section == 'outwear':
            for option in config.options(section):
                params[option] = eval(config.get(section, option))
        if section == 'skirt':
            for option in config.options(section):
                params[option] = eval(config.get(section, option))
        if section == 'trousers':
            for option in config.options(section):
                params[option] = eval(config.get(section, option))
    return params

'''
    load the model
'''
cpn_model = importlib.import_module('models.nets.' + FLAGS.network_def)
datagenerator_config_file = FLAGS.datagenerator_config_file

def train():

    """
        Step 1: Create dirs for saving models and logs
    """
    model_path_suffix = os.path.join(FLAGS.network_def,
                                    'input_{}_output_{}'.format(FLAGS.input_size, FLAGS.heatmap_size),
                                    'joints_{}'.format(FLAGS.num_of_joints),
                                    'init_{}_rate_{}_step_{}'.format(FLAGS.init_lr, FLAGS.lr_decay_rate,FLAGS.lr_decay_step)
                                    )
    model_save_dir = os.path.join('dress_results','models','weights',model_path_suffix)

    train_log_save_dir = os.path.join('dress_results','models','logs',model_path_suffix,'train')

    test_log_save_dir = os.path.join('dress_results','models','logs', model_path_suffix, 'test')
    os.system('mkdir -p {}'.format(model_save_dir))
    os.system('mkdir -p {}'.format(train_log_save_dir))
    os.system('mkdir -p {}'.format(test_log_save_dir))
    
    """ 
        Step 2: Create dataset and data generator
    """
    print('--Parsing Config File')
    params = process_config(datagenerator_config_file)
    print('--Creating Dataset')
    dataset = DataGenerator(params['total_joints_list'], params['blouse_joints_list'], params['dress_joints_list'],
                            params['outwear_joints_list'], params['skirt_joints_list'], params['trousers_joints_list'],
                            params['blouse_index'], params['dress_index'], params['outwear_index'], params['skirt_index'],
                            params['trousers_index'], params['img_directory'], params['training_data_file'])
    dataset.generate_set(rand=True, validationRate=0.15)
    generator = dataset.generator(batchSize=FLAGS.batch_size, norm=False, sample='train')
    generator_eval = dataset.generator(batchSize=FLAGS.batch_size, norm=False, sample='valid')

    """ 
        Step 3: Build network graph
    """
    model = cpn_model.CPN_Model(input_size=FLAGS.input_size,
                                total_num= FLAGS.total_num
                                heatmap_size=FLAGS.heatmap_size,
                                batch_size=FLAGS.batch_size,
                                joints=FLAGS.num_of_joints,
                                img_type=FLAGS.color_channel,
                                is_training=True)
    
    model.build_loss_ohkm( FLAGS.init_lr, FLAGS.lr_decay_rate, FLAGS.lr_decay_step, optimizer='Adam')
    print('=====Model Build=====\n')

    merged_summary = tf.summary.merge_all()
    
    """ 
        Step 4: Training
    """
    
    with tf.Session(config=tf.ConfigProto(log_device_placement=True,allow_soft_placement=True)) as sess:
        # Create tensorboard
        train_writer = tf.summary.FileWriter(train_log_save_dir, sess.graph)
        test_writer = tf.summary.FileWriter(test_log_save_dir, sess.graph)
        # Create model saver
        saver = tf.train.Saver(max_to_keep=None)
        # Init all vars
        init_op = tf.global_variables_initializer()
        sess.run(init_op)
        
        '''
        # Restore pretrained weights
        if FLAGS.pretrained_model != '':
            if FLAGS.pretrained_model.endswith('.pkl'):
                model.load_weights_from_file(FLAGS.pretrained_model, sess, finetune=True)
                # Check weights
                for variable in tf.trainable_variables():
                    with tf.variable_scope('', reuse=True):
                        var = tf.get_variable(variable.name.split(':0')[0])
                        print(variable.name, np.mean(sess.run(var)))
            else:
                checkpoint = tf.train.get_checkpoint_state(FLAGS.pretrained_model)
                # 获取最新保存的模型检查点文件
                ckpt = checkpoint.model_checkpoint_path
                saver.restore(sess, ckpt)
                # check weights
                for variable in tf.trainable_variables():
                    with tf.variable_scope('', reuse=True):
                        var = tf.get_variable(variable.name.split(':0')[0])
                        print(variable.name, np.mean(sess.run(var)))
        
        '''
        for training_itr in range(FLAGS.training_iters):
            t1 = time.time()

            """ 
                highlight：DataGenerator
            """
            # Read one batch data
            batch_x_np, batch_gt_heatmap_np, batch_centermap, batch_weight_np = next(generator)


            if FLAGS.normalize_img:
                # Normalize images
                batch_x_np = batch_x_np / 255.0 - 0.5
            else:
                batch_x_np -= 128.0

            
            # Forward and update weights
            global_loss_np, refine_loss_np, total_loss_np, _,  summaries, current_lr, \
            global_step = sess.run([model.global_loss,
                                    model.refine_loss,
                                    model.total_loss,
                                    model.train_op,
                                    merged_summary,
                                    model.lr,
                                    model.global_step
                                    ],
                                    feed_dict={model.input_images: batch_x_np,
                                            model.cmap_placeholder: batch_centermap,
                                            model.gt_hmap_placeholder: batch_gt_heatmap_np,
                                            model.train_weights_placeholder: batch_weight_np})

            # Show training info
            print_current_training_stats(global_step, current_lr, global_loss_np,refine_loss_np,total_loss_np, time.time() - t1)

            # Write logs
            train_writer.add_summary(summaries, global_step)

            if (global_step + 1) % FLAGS.validation_iters == 0:
                mean_val_loss = 0
                cnt = 0

                while cnt < 10:
                    batch_x_np, batch_gt_heatmap_np, batch_centermap, batch_weight_np = next(generator_eval)

                    # Normalize images
                    batch_x_np = batch_x_np / 255.0 - 0.5
                    total_loss_np, summaries = sess.run([model.total_loss, merged_summary],
                                                        feed_dict={model.input_images: batch_x_np,
                                                                   model.cmap_placeholder: batch_centermap,
                                                                   model.gt_hmap_placeholder: batch_gt_heatmap_np,
                                                                   model.train_weights_placeholder: batch_weight_np})
                    mean_val_loss += total_loss_np
                    cnt += 1

                print('\nValidation loss: {:>7.2f}\n'.format(mean_val_loss / cnt))
                test_writer.add_summary(summaries, global_step)

            # Save models
            if (global_step + 1) % FLAGS.model_save_iters == 0:
                saver.save(sess=sess, save_path=model_save_dir + '/' + FLAGS.network_def.split('.py')[0],
                           global_step=(global_step + 1))
                print('\nModel checkpoint saved...\n')

            # Finish training
            if global_step == FLAGS.training_iters:
                saver.save(sess=sess, save_path=model_save_dir + '/' + FLAGS.network_def.split('.py')[0],
                           global_step=(global_step + 1))
                print('\nModel checkpoint saved...\n')
                break
    print('Training done.')


def print_current_training_stats(global_step, cur_lr, global_loss_np, refine_loss_np, total_loss, time_elapsed):
    stats = 'Step: {}/{} ----- Cur_lr: {:1.7f} ----- Time: {:>2.2f} sec.'.format(global_step, FLAGS.training_iters,
                                                                                 cur_lr, time_elapsed)
    losses = ' | '.join(
        ['global_loss: {:>7.2f}'.format(global_loss_np) ,'refine_loss: {:>7.2f}'.format(refine_loss_np)])
    losses += ' | Total loss: {}'.format(total_loss)
    print(stats)
    print(losses + '\n')


if __name__ == '__main__':
    train()
