import time
import keras

# from keras.models import Sequential
# from keras.layers import (
#     Activation, Conv2D, Dense,
#     Dropout, BatchNormalization, Flatten,
#     MaxPooling2D
# )
import keras.backend.tensorflow_backend as K

from autoda.data_augmentation import ImageAugmentation

from autoda.networks.utils import (
    _update_history, get_input_shape,
)
from autoda.networks.architectures import ARCHITECTURES


def objective_function(data, configuration=None, benchmark="AlexNet", max_epochs=40, batch_size=512, time_budget=900):

    # preprocess data
    x_train, y_train, x_validation, y_validation, x_test, y_test, data_mean, data_variance = data

    input_shape = get_input_shape(x_train)  # NWHC

    num_classes = y_train.shape[1]

    train_history, runtime = {}, []

    used_budget, num_epochs, duration_last_epoch = 0., 0, 0.
    num_datapoints, *_ = x_train.shape

    start_time = time.time()

    config = K.tf.ConfigProto(log_device_placement=False, allow_soft_placement=True)
    session = K.tf.Session(config=config)
    K.set_session(session)

    assert benchmark in ARCHITECTURES
    # AlexNet
    network_function = ARCHITECTURES[benchmark]
    model = network_function(num_classes=num_classes, input_shape=input_shape)

    with K.tf.device("/gpu:1"):
        with session.graph.as_default():
            opt = keras.optimizers.Adam(lr=0.0016681005372000575)

            # Let's train the model using RMSprop
            model.compile(loss='categorical_crossentropy',
                          optimizer=opt,
                          metrics=['accuracy'])

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

            validation_loss, validation_accuracy = model.evaluate(x_validation, y_validation, verbose=0)

    result = {
        "validation_loss": validation_loss,
        "validation_error": 1 - validation_accuracy,
        "used_budget": used_budget,
        "train_history": train_history,
        "configs": configuration
    }

    if configuration:
        result["configs"] = configuration.get_dictionary()
    else:
        result["configs"] = {}

    return result
