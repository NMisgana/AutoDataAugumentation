import time

import keras
import keras.backend.tensorflow_backend as K
from sklearn.model_selection import train_test_split

from autoda.data_augmentation import ImageAugmentation

from autoda.networks.utils import (
    get_num_classes, _update_history, get_data, get_input_shape,
    compute_zero_mean_unit_variance, normalize,
    enforce_image_format
)
from autoda.networks.architectures import ARCHITECTURES


@enforce_image_format("channels_last")
def preprocess_data(x_train, y_train, x_test, y_test, augment):

    num_classes = get_num_classes(y_train)

    img_rows, img_cols = x_train.shape[2], x_train.shape[2]
    # reshape 3D image to 4D
    if x_train.ndim == 3:
        x_train = x_train.reshape(x_train.shape[0], img_rows, img_cols, 1)
        x_test = x_test.reshape(x_test.shape[0], img_rows, img_cols, 1)

    # compute zero mean and unit variance for normalization
    mean, variance = compute_zero_mean_unit_variance(x_train)

    x_train, x_valid, y_train, y_valid = train_test_split(x_train, y_train, test_size=0.2)

    if not augment:
        print("normalize training set beforehand if no data_augmentation")
        x_train = normalize(x_train, mean, variance)
    x_valid = normalize(x_valid, mean, variance)
    x_test = normalize(x_test, mean, variance)

    # dimensions of data
    print(x_train.shape, 'x_train Dimensions')
    print(x_train.shape[0], 'train samples')
    print(x_valid.shape[0], 'validation samples')
    print(x_test.shape[0], 'test samples')

    # Convert class vectors to binary class matrices.
    y_train = keras.utils.to_categorical(y_train, num_classes)
    y_valid = keras.utils.to_categorical(y_valid, num_classes)
    y_test = keras.utils.to_categorical(y_test, num_classes)

    print("Y_train_after:", y_train.shape[1])

    return x_train, y_train, x_valid, y_valid, x_test, y_test, mean, variance


def train_model(model, train_data, validation_data, data_mean, data_variance,
                batch_size=512, configuration=None,
                time_budget=900, max_epochs=40, ):

    x_train, y_train = train_data
    x_validation, y_validation = validation_data

    train_history, runtime = {}, []

    used_budget, num_epochs, duration_last_epoch = 0., 0, 0.
    num_datapoints, *_ = x_train.shape

    start_time = time.time()

    while(num_epochs < max_epochs) and \
            (used_budget + 1.11 * duration_last_epoch < time_budget):
        if configuration:
            print("Using real-time data augmentation.")

            augmenter = ImageAugmentation(configuration)

            # Fit the model on the batches augmented data generated by apply transform
            history = model.fit_generator(
                augmenter.apply_transform(
                    x_train, y_train,
                    data_mean, data_variance,
                    batch_size=batch_size
                ),
                steps_per_epoch=num_datapoints // batch_size,
                epochs=num_epochs + 1,
                validation_data=(x_validation, y_validation),
                initial_epoch=num_epochs
            )
        else:
            print('Not using data augmentation.')

            history = model.fit(
                x_train, y_train,
                batch_size=batch_size,
                epochs=num_epochs + 1,
                validation_data=(x_validation, y_validation),
                initial_epoch=num_epochs,
                shuffle=True
            )

            train_history = _update_history(train_history, history.history)

        num_epochs += len(history.history.get("loss", []))
        duration_last_epoch = (time.time() - start_time) - used_budget
        used_budget += duration_last_epoch
        print("used_budget", used_budget, "duration_last_epoch", duration_last_epoch, "time_budget", time_budget)
        runtime.append(time.time() - start_time)

    return runtime, used_budget, train_history


def train_evaluate(model, train_data, validation_data, data_mean, data_variance,
                   batch_size=512, configuration=None,
                   time_budget=900, max_epochs=40, ):

    runtime, used_budget, train_history = train_model(
        model, train_data, validation_data, data_mean, data_variance,
        batch_size, configuration, time_budget, max_epochs
    )

    # Evaluate model with test data set and share sample prediction results
    # XXX: Figure out where the loss is located in "model.evaluate"
    # return values and also include it in result
    _, validation_accuracy, *_ = model.evaluate(*validation_data, verbose=0)

    result = {
        "train_accuracy": train_history["acc"][-1],
        "validation_loss": train_history["val_loss"][-1],
        "validation_error": 1 - validation_accuracy,
        "used_budget": used_budget,
        "train_history": train_history,
    }

    if configuration:
        result["configs"] = configuration.get_dictionary()
    else:
        result["configs"] = {}

    return result


def objective_function(sample_config=None, dataset="cifar10", benchmark="AlexNet", max_epochs=40, batch_size=512):

    # load data
    x_train, y_train, x_test, y_test = get_data(dataset)

    augment = sample_config is not None

    # preprocess data
    x_train, y_train, x_valid, y_valid, x_test, y_test, mean, variance = preprocess_data(x_train, y_train, x_test, y_test, augment)

    input_shape = get_input_shape(x_train)  # NWHC

    num_classes = y_train.shape[1]
    print("after", num_classes)

    with K.tf.device('/gpu:1'):

        K.set_session(K.tf.Session(config=K.tf.ConfigProto(allow_soft_placement=True, log_device_placement=False)))

        assert benchmark in ARCHITECTURES
        # AlexNet
        network_function = ARCHITECTURES[benchmark]
        model = network_function(num_classes=num_classes, input_shape=input_shape)

        return train_evaluate(
            model=model, train_data=(x_train, y_train),
            validation_data=(x_valid, y_valid),
            data_mean=mean, data_variance=variance,
            configuration=sample_config
        )
