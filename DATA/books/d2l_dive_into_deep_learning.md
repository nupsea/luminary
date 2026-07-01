# Introduction

Until recently, nearly every computer program
that you might have interacted with during
an ordinary day
was coded up as a rigid set of rules
specifying precisely how it should behave.
Say that we wanted to write an application
to manage an e-commerce platform.
After huddling around a whiteboard
for a few hours to ponder the problem,
we might settle on the broad strokes
of a working solution, for example:
(i) users interact with the application through an interface
running in a web browser or mobile application;
(ii) our application interacts with a commercial-grade database engine
to keep track of each user's state and maintain records
of historical transactions;
and (iii) at the heart of our application,
the *business logic* (you might say, the *brains*) of our application
spells out a set of rules that map every conceivable circumstance
to the corresponding action that our program should take.

To build the brains of our application,
we might enumerate all the common events
that our program should handle.
For example, whenever a customer clicks
to add an item to their shopping cart,
our program should add an entry
to the shopping cart database table,
associating that user's ID
with the requested product's ID.
We might then attempt to step through
every possible corner case,
testing the appropriateness of our rules
and making any necessary modifications.
What happens if a user
initiates a purchase with an empty cart?
While few developers ever get it
completely right the first time
(it might take some test runs to work out the kinks),
for the most part we can write such programs
and confidently launch them
*before* ever seeing a real customer.
Our ability to manually design automated systems
that drive functioning products and systems,
often in novel situations,
is a remarkable cognitive feat.
And when you are able to devise solutions
that work $100\%$ of the time,
you typically should not be
worrying about machine learning.

Fortunately for the growing community
of machine learning scientists,
many tasks that we would like to automate
do not bend so easily to human ingenuity.
Imagine huddling around the whiteboard
with the smartest minds you know,
but this time you are tackling
one of the following problems:

* Write a program that predicts tomorrow's weather given geographic information, satellite images, and a trailing window of past weather.
* Write a program that takes in a factoid question, expressed in free-form text, and  answers it correctly.
* Write a program that, given an image, identifies every person depicted in it and draws outlines around each.
* Write a program that presents users with products that they are likely to enjoy but unlikely, in the natural course of browsing, to encounter.

For these problems,
even elite programmers would struggle
to code up solutions from scratch.
The reasons can vary.
Sometimes the program that we are looking for
follows a pattern that changes over time,
so there is no fixed right answer!
In such cases, any successful solution
must adapt gracefully to a changing world.
At other times, the relationship (say between pixels,
and abstract categories) may be too complicated,
requiring thousands or millions of computations
and following unknown principles.
In the case of image recognition,
the precise steps required to perform the task
lie beyond our conscious understanding,
even though our subconscious cognitive processes
execute the task effortlessly.

*Machine learning* is the study of algorithms
that can learn from experience.
As a machine learning algorithm accumulates more experience,
typically in the form of observational data
or interactions with an environment,
its performance improves.
Contrast this with our deterministic e-commerce platform,
which follows the same business logic,
no matter how much experience accrues,
until the developers themselves learn and decide
that it is time to update the software.
In this book, we will teach you
the fundamentals of machine learning,
focusing in particular on *deep learning*,
a powerful set of techniques
driving innovations in areas as diverse as computer vision,
natural language processing, healthcare, and genomics.

## A Motivating Example

Before beginning writing, the authors of this book,
like much of the work force, had to become caffeinated.
We hopped in the car and started driving.
Using an iPhone, Alex called out "Hey Siri",
awakening the phone's voice recognition system.
Then Mu commanded "directions to Blue Bottle coffee shop".
The phone quickly displayed the transcription of his command.
It also recognized that we were asking for directions
and launched the Maps application (app)
to fulfill our request.
Once launched, the Maps app identified a number of routes.
Next to each route, the phone displayed a predicted transit time.
While this story was fabricated for pedagogical convenience,
it demonstrates that in the span of just a few seconds,
our everyday interactions with a smart phone
can engage several machine learning models.

Imagine just writing a program to respond to a *wake word*
such as "Alexa", "OK Google", and "Hey Siri".
Try coding it up in a room by yourself
with nothing but a computer and a code editor,
as illustrated in .
How would you write such a program from first principles?
Think about it... the problem is hard.
Every second, the microphone will collect roughly
44,000 samples.
Each sample is a measurement of the amplitude of the sound wave.
What rule could map reliably from a snippet of raw audio to confident predictions
$\{\textrm{yes}, \textrm{no}\}$
about whether the snippet contains the wake word?
If you are stuck, do not worry.
We do not know how to write such a program from scratch either.
That is why we use machine learning.

Here is the trick.
Often, even when we do not know how to tell a computer
explicitly how to map from inputs to outputs,
we are nonetheless capable of performing the cognitive feat ourselves.
In other words, even if you do not know
how to program a computer to recognize the word "Alexa",
you yourself are able to recognize it.
Armed with this ability, we can collect a huge *dataset*
containing examples of audio snippets and associated labels,
indicating which snippets contain the wake word.
In the currently dominant approach to machine learning,
we do not attempt to design a system
*explicitly* to recognize wake words.
Instead, we define a flexible program
whose behavior is determined by a number of *parameters*.
Then we use the dataset to determine the best possible parameter values,
i.e., those that improve the performance of our program
with respect to a chosen performance measure.

You can think of the parameters as knobs that we can turn,
manipulating the behavior of the program.
Once the parameters are fixed, we call the program a *model*.
The set of all distinct programs (input--output mappings)
that we can produce just by manipulating the parameters
is called a *family* of models.
And the "meta-program" that uses our dataset
to choose the parameters is called a *learning algorithm*.

Before we can go ahead and engage the learning algorithm,
we have to define the problem precisely,
pinning down the exact nature of the inputs and outputs,
and choosing an appropriate model family.
In this case,
our model receives a snippet of audio as *input*,
and the model
generates a selection among
$\{\textrm{yes}, \textrm{no}\}$ as *output*.
If all goes according to plan
the model's guesses will
typically be correct as to
whether the snippet contains the wake word.

If we choose the right family of models,
there should exist one setting of the knobs
such that the model fires "yes" every time it hears the word "Alexa".
Because the exact choice of the wake word is arbitrary,
we will probably need a model family sufficiently rich that,
via another setting of the knobs, it could fire "yes"
only upon hearing the word "Apricot".
We expect that the same model family should be suitable
for "Alexa" recognition and "Apricot" recognition
because they seem, intuitively, to be similar tasks.
However, we might need a different family of models entirely
if we want to deal with fundamentally different inputs or outputs,
say if we wanted to map from images to captions,
or from English sentences to Chinese sentences.

As you might guess, if we just set all of the knobs randomly,
it is unlikely that our model will recognize "Alexa",
"Apricot", or any other English word.
In machine learning,
the *learning* is the process
by which we discover the right setting of the knobs
for coercing the desired behavior from our model.
In other words,
we *train* our model with data.
As shown in , the training process usually looks like the following:

1. Start off with a randomly initialized model that cannot do anything useful.
1. Grab some of your data (e.g., audio snippets and corresponding $\{\textrm{yes}, \textrm{no}\}$ labels).
1. Tweak the knobs to make the model perform better as assessed on those examples.
1. Repeat Steps 2 and 3 until the model is awesome.

To summarize, rather than code up a wake word recognizer,
we code up a program that can *learn* to recognize wake words,
if presented with a large labeled dataset.
You can think of this act of determining a program's behavior
by presenting it with a dataset as *programming with data*.
That is to say, we can "program" a cat detector
by providing our machine learning system
with many examples of cats and dogs.
This way the detector will eventually learn to emit
a very large positive number if it is a cat,
a very large negative number if it is a dog,
and something closer to zero if it is not sure.
This barely scratches the surface of what machine learning can do.
Deep learning, which we will explain in greater detail later,
is just one among many popular methods
for solving machine learning problems.

## Key Components

In our wake word example, we described a dataset
consisting of audio snippets and binary labels,
and we gave a hand-wavy sense of how we might train
a model to approximate a mapping from snippets to classifications.
This sort of problem,
where we try to predict a designated unknown label
based on known inputs
given a dataset consisting of examples
for which the labels are known,
is called *supervised learning*.
This is just one among many kinds of machine learning problems.
Before we explore other varieties,
we would like to shed more light
on some core components that will follow us around,
no matter what kind of machine learning problem we tackle:

1. The *data* that we can learn from.
1. A *model* of how to transform the data.
1. An *objective function* that quantifies how well (or badly) the model is doing.
1. An *algorithm* to adjust the model's parameters to optimize the objective function.

### Data

It might go without saying that you cannot do data science without data.
We could lose hundreds of pages pondering what precisely data *is*,
but for now, we will focus on the key properties
of the datasets that we will be concerned with.
Generally, we are concerned with a collection of examples.
In order to work with data usefully, we typically
need to come up with a suitable numerical representation.
Each *example* (or *data point*, *data instance*, *sample*)
typically consists of a set of attributes
called *features* (sometimes called *covariates* or *inputs*),
based on which the model must make its predictions.
In supervised learning problems,
our goal is to predict the value of a special attribute,
called the *label* (or *target*),
that is not part of the model's input.

If we were working with image data,
each example might consist of an
individual photograph (the features)
and a number indicating the category
to which the photograph belongs (the label).
The photograph would be represented numerically
as three grids of numerical values representing
the brightness of red, green, and blue light
at each pixel location.
For example, a $200\times 200$ pixel color photograph
would consist of $200\times200\times3=120000$ numerical values.

Alternatively, we might work with electronic health record data
and tackle the task of predicting the likelihood
that a given patient  will survive the next 30 days.
Here, our features might consist of a collection
of readily available attributes
and frequently recorded measurements,
including age, vital signs, comorbidities,
current medications, and recent procedures.
The label available for training would be a binary value
indicating whether each patient in the historical data
survived within the 30-day window.

In such cases, when every example is characterized
by the same number of numerical features,
we say that the inputs are fixed-length vectors
and we call the (constant) length of the vectors
the *dimensionality* of the data.
As you might imagine, fixed-length inputs can be convenient,
giving us one less complication to worry about.
However, not all data can easily
be represented as *fixed-length* vectors.
While we might expect microscope images
to come from standard equipment,
we cannot expect images mined from the Internet
all to have the same resolution or shape.
For images, we might consider
cropping them to a standard size,
but that strategy only gets us so far.
We risk losing information in the cropped-out portions.
Moreover, text data resists fixed-length
representations even more stubbornly.
Consider the customer reviews left
on e-commerce sites such as Amazon, IMDb, and TripAdvisor.
Some are short: "it stinks!".
Others ramble for pages.
One major advantage of deep learning over traditional methods
is the comparative grace with which modern models
can handle *varying-length* data.

Generally, the more data we have, the easier our job becomes.
When we have more data, we can train more powerful models
and rely less heavily on preconceived assumptions.
The regime change from (comparatively) small to big data
is a major contributor to the success of modern deep learning.
To drive the point home, many of
the most exciting models in deep learning
do not work without large datasets.
Some others might work in the small data regime,
but are no better than traditional approaches.

Finally, it is not enough to have lots of data
and to process it cleverly.
We need the *right* data.
If the data is full of mistakes,
or if the chosen features are not predictive
of the target quantity of interest,
learning is going to fail.
The situation is captured well by the cliché:
*garbage in, garbage out*.
Moreover, poor predictive performance
is not the only potential consequence.
In sensitive applications of machine learning,
like predictive policing, resume screening,
and risk models used for lending,
we must be especially alert
to the consequences of garbage data.
One commonly occurring failure mode concerns datasets
where some groups of people are unrepresented
in the training data.
Imagine applying a skin cancer recognition system
that had never seen black skin before.
Failure can also occur when the data
does not only under-represent some groups
but reflects societal prejudices.
For example, if past hiring decisions
are used to train a predictive model
that will be used to screen resumes
then machine learning models could inadvertently
capture and automate historical injustices.
Note that this can all happen without the data scientist
actively conspiring, or even being aware.

### Models

Most machine learning involves transforming the data in some sense.
We might want to build a system that ingests photos and predicts smiley-ness.
Alternatively,
we might want to ingest a set of sensor readings
and predict how normal vs. anomalous the readings are.
By *model*, we denote the computational machinery for ingesting data
of one type,
and spitting out predictions of a possibly different type.
In particular, we are interested in *statistical models*
that can be estimated from data.
While simple models are perfectly capable of addressing
appropriately simple problems,
the problems
that we focus on in this book stretch the limits of classical methods.
Deep learning is differentiated from classical approaches
principally by the set of powerful models that it focuses on.
These models consist of many successive transformations of the data
that are chained together top to bottom, thus the name *deep learning*.
On our way to discussing deep models,
we will also discuss some more traditional methods.

### Objective Functions

Earlier, we introduced machine learning as learning from experience.
By *learning* here,
we mean improving at some task over time.
But who is to say what constitutes an improvement?
You might imagine that we could propose updating our model,
and some people might disagree on whether our proposal
constituted an improvement or not.

In order to develop a formal mathematical system of learning machines,
we need to have formal measures of how good (or bad) our models are.
In machine learning, and optimization more generally,
we call these *objective functions*.
By convention, we usually define objective functions
so that lower is better.
This is merely a convention.
You can take any function
for which higher is better, and turn it into a new function
that is qualitatively identical but for which lower is better
by flipping the sign.
Because we choose lower to be better, these functions are sometimes called
*loss functions*.

When trying to predict numerical values,
the most common loss function is *squared error*,
i.e., the square of the difference between
the prediction and the ground truth target.
For classification, the most common objective
is to minimize error rate,
i.e., the fraction of examples on which
our predictions disagree with the ground truth.
Some objectives (e.g., squared error) are easy to optimize,
while others (e.g., error rate) are difficult to optimize directly,
owing to non-differentiability or other complications.
In these cases, it is common instead to optimize a *surrogate objective*.

During optimization, we think of the loss
as a function of the model's parameters,
and treat the training dataset as a constant.
We learn
the best values of our model's parameters
by minimizing the loss incurred on a set
consisting of some number of examples collected for training.
However, doing well on the training data
does not guarantee that we will do well on unseen data.
So we will typically want to split the available data into two partitions:
the *training dataset* (or *training set*), for learning model parameters;
and the *test dataset* (or *test set*), which is held out for evaluation.
At the end of the day, we typically report
how our models perform on both partitions.
You could think of training performance
as analogous to the scores that a student achieves
on the practice exams used to prepare for some real final exam.
Even if the results are encouraging,
that does not guarantee success on the final exam.
Over the course of studying, the student
might begin to memorize the practice questions,
appearing to master the topic but faltering
when faced with previously unseen questions
on the actual final exam.
When a model performs well on the training set
but fails to generalize to unseen data,
we say that it is *overfitting* to the training data.

### Optimization Algorithms

Once we have got some data source and representation,
a model, and a well-defined objective function,
we need an algorithm capable of searching
for the best possible parameters for minimizing the loss function.
Popular optimization algorithms for deep learning
are based on an approach called *gradient descent*.
In brief, at each step, this method
checks to see, for each parameter,
how that training set loss would change
if you perturbed that parameter by just a small amount.
It would then update the parameter
in the direction that lowers the loss.

## Kinds of Machine Learning Problems

The wake word problem in our motivating example
is just one among many
that machine learning can tackle.
To motivate the reader further
and provide us with some common language
that will follow us throughout the book,
we now provide a broad overview of the landscape
of machine learning problems.

### Supervised Learning

Supervised learning describes tasks
where we are given a dataset
containing both features and labels
and
asked to produce a model that predicts the labels when
given input features.
Each feature--label pair is called an example.
Sometimes, when the context is clear,
we may use the term *examples*
to refer to a collection of inputs,
even when the corresponding labels are unknown.
The supervision comes into play
because, for choosing the parameters,
we (the supervisors) provide the model
with a dataset consisting of labeled examples.
In probabilistic terms, we typically are interested in estimating
the conditional probability of a label given input features.
While it is just one among several paradigms,
supervised learning accounts for the majority of successful
applications of machine learning in industry.
Partly that is because many important tasks
can be described crisply as estimating the probability
of something unknown given a particular set of available data:

* Predict cancer vs. not cancer, given a computer tomography image.
* Predict the correct translation in French, given a sentence in English.
* Predict the price of a stock next month based on this month's financial reporting data.

While all supervised learning problems
are captured by the simple description
"predicting the labels given input features",
supervised learning itself can take diverse forms
and require tons of modeling decisions,
depending on (among other considerations)
the type, size, and quantity of the inputs and outputs.
For example, we use different models
for processing sequences of arbitrary lengths
and fixed-length vector representations.
We will visit many of these problems
in depth throughout this book.

Informally, the learning process looks something like the following.
First, grab a big collection of examples for which the features are known
and select from them a random subset,
acquiring the ground truth labels for each.
Sometimes these labels might be available data that have already been collected
(e.g., did a patient die within the following year?)
and other times we might need to employ human annotators to label the data,
(e.g., assigning images to categories).
Together, these inputs and corresponding labels comprise the training set.
We feed the training dataset into a supervised learning algorithm,
a function that takes as input a dataset
and outputs another function: the learned model.
Finally, we can feed previously unseen inputs to the learned model,
using its outputs as predictions of the corresponding label.
The full process is drawn in .

#### Regression

Perhaps the simplest supervised learning task
to wrap your head around is *regression*.
Consider, for example, a set of data harvested
from a database of home sales.
We might construct a table,
in which each row corresponds to a different house,
and each column corresponds to some relevant attribute,
such as the square footage of a house,
the number of bedrooms, the number of bathrooms,
and the number of minutes (walking) to the center of town.
In this dataset, each example would be a specific house,
and the corresponding feature vector would be one row in the table.
If you live in New York or San Francisco,
and you are not the CEO of Amazon, Google, Microsoft, or Facebook,
the (sq. footage, no. of bedrooms, no. of bathrooms, walking distance)
feature vector for your home might look something like: $[600, 1, 1, 60]$.
However, if you live in Pittsburgh, it might look more like $[3000, 4, 3, 10]$.
Fixed-length feature vectors like this are essential
for most classic machine learning algorithms.

What makes a problem a regression is actually
the form of the target.
Say that you are in the market for a new home.
You might want to estimate the fair market value of a house,
given some features such as above.
The data here might consist of historical home listings
and the labels might be the observed sales prices.
When labels take on arbitrary numerical values
(even within some interval),
we call this a *regression* problem.
The goal is to produce a model whose predictions
closely approximate the actual label values.

Lots of practical problems are easily described as regression problems.
Predicting the rating that a user will assign to a movie
can be thought of as a regression problem
and if you designed a great algorithm
to accomplish this feat in 2009,
you might have won the [1-million-dollar Netflix prize](https://en.wikipedia.org/wiki/Netflix_Prize).
Predicting the length of stay for patients in the hospital
is also a regression problem.
A good rule of thumb is that any *how much?* or *how many?* problem
is likely to be regression. For example:

* How many hours will this surgery take?
* How much rainfall will this town have in the next six hours?

Even if you have never worked with machine learning before,
you have probably worked through a regression problem informally.
Imagine, for example, that you had your drains repaired
and that your contractor spent 3 hours
removing gunk from your sewage pipes.
Then they sent you a bill of 350 dollars.
Now imagine that your friend hired the same contractor for 2 hours
and received a bill of 250 dollars.
If someone then asked you how much to expect
on their upcoming gunk-removal invoice
you might make some reasonable assumptions,
such as more hours worked costs more dollars.
You might also assume that there is some base charge
and that the contractor then charges per hour.
If these assumptions held true, then given these two data examples,
you could already identify the contractor's pricing structure:
100 dollars per hour plus 50 dollars to show up at your house.
If you followed that much, then you already understand
the high-level idea behind *linear* regression.

In this case, we could produce the parameters
that exactly matched the contractor's prices.
Sometimes this is not possible,
e.g., if some of the variation
arises from factors beyond your two features.
In these cases, we will try to learn models
that minimize the distance between our predictions and the observed values.
In most of our chapters, we will focus on
minimizing the squared error loss function.
As we will see later, this loss corresponds to the assumption
that our data were corrupted by Gaussian noise.

#### Classification

While regression models are great
for addressing *how many?* questions,
lots of problems do not fit comfortably in this template.
Consider, for example, a bank that wants
to develop a check scanning feature for its mobile app.
Ideally, the customer would simply snap a photo of a check
and the app would automatically recognize the text from the image.
Assuming that we had some ability
to segment out image patches
corresponding to each handwritten character,
then the primary remaining task would be
to determine which character among some known set
is depicted in each image patch.
These kinds of *which one?* problems are called *classification*
and require a different set of tools
from those used for regression,
although many techniques will carry over.

In *classification*, we want our model to look at features,
e.g., the pixel values in an image,
and then predict to which *category*
(sometimes called a *class*)
among some discrete set of options,
an example belongs.
For handwritten digits, we might have ten classes,
corresponding to the digits 0 through 9.
The simplest form of classification is when there are only two classes,
a problem which we call *binary classification*.
For example, our dataset could consist of images of animals
and our labels  might be the classes $\textrm{\{cat, dog\}}$.
Whereas in regression we sought a regressor to output a numerical value,
in classification we seek a classifier,
whose output is the predicted class assignment.

For reasons that we will get into as the book gets more technical,
it can be difficult to optimize a model that can only output
a *firm* categorical assignment,
e.g., either "cat" or "dog".
In these cases, it is usually much easier to express
our model in the language of probabilities.
Given features of an example,
our model assigns a probability
to each possible class.
Returning to our animal classification example
where the classes are $\textrm{\{cat, dog\}}$,
a classifier might see an image and output the probability
that the image is a cat as 0.9.
We can interpret this number by saying that the classifier
is 90\% sure that the image depicts a cat.
The magnitude of the probability for the predicted class
conveys a notion of uncertainty.
It is not the only one available
and we will discuss others in chapters dealing with more advanced topics.

When we have more than two possible classes,
we call the problem *multiclass classification*.
Common examples include handwritten character recognition
$\textrm{\{0, 1, 2, ... 9, a, b, c, ...\}}$.
While we attacked regression problems by trying
to minimize the squared error loss function,
the common loss function for classification problems is called *cross-entropy*,
whose name will be demystified
when we introduce information theory in later chapters.

Note that the most likely class is not necessarily
the one that you are going to use for your decision.
Assume that you find a beautiful mushroom in your backyard
as shown in .

Now, assume that you built a classifier and trained it
to predict whether a mushroom is poisonous based on a photograph.
Say our poison-detection classifier outputs
that the probability that
In other words, the classifier is 80\% sure
that our mushroom is not a death cap.
Still, you would have to be a fool to eat it.
That is because the certain benefit of a delicious dinner
is not worth a 20\% risk of dying from it.
In other words, the effect of the uncertain risk
outweighs the benefit by far.
Thus, in order to make a decision about whether to eat the mushroom,
we need to compute the expected detriment
associated with each action
which depends both on the likely outcomes
and the benefits or harms associated with each.
In this case, the detriment incurred
by eating the mushroom
might be $0.2 \times \infty + 0.8 \times 0 = \infty$,
whereas the loss of discarding it
is $0.2 \times 0 + 0.8 \times 1 = 0.8$.
Our caution was justified:
as any mycologist would tell us,
the mushroom in
is actually a death cap.

Classification can get much more complicated than just
binary or multiclass classification.
For instance, there are some variants of classification
addressing hierarchically structured classes.
In such cases not all errors are equal---if
we must err, we might prefer to misclassify
to a related class rather than a distant class.
Usually, this is referred to as *hierarchical classification*.
For inspiration, you might think of [Linnaeus](https://en.wikipedia.org/wiki/Carl_Linnaeus),
who organized fauna in a hierarchy.

In the case of animal classification,
it might not be so bad to mistake
a poodle for a schnauzer,
but our model would pay a huge penalty
if it confused a poodle with a dinosaur.
Which hierarchy is relevant might depend
on how you plan to use the model.
For example, rattlesnakes and garter snakes
might be close on the phylogenetic tree,
but mistaking a rattler for a garter could have fatal consequences.

#### Tagging

Some classification problems fit neatly
into the binary or multiclass classification setups.
For example, we could train a normal binary classifier
to distinguish cats from dogs.
Given the current state of computer vision,
we can do this easily, with off-the-shelf tools.
Nonetheless, no matter how accurate our model gets,
we might find ourselves in trouble when the classifier
encounters an image of the *Town Musicians of Bremen*,
a popular German fairy tale featuring four animals
().

As you can see, the photo features a cat,
a rooster, a dog, and a donkey,
with some trees in the background.
If we anticipate encountering such images,
multiclass classification might not be
the right problem formulation.
Instead, we might want to give the model the option of
saying the image depicts a cat, a dog, a donkey,
*and* a rooster.

The problem of learning to predict classes that are
not mutually exclusive is called *multi-label classification*.
Auto-tagging problems are typically best described
in terms of multi-label classification.
Think of the tags people might apply
to posts on a technical blog,
e.g., "machine learning", "technology", "gadgets",
"programming languages", "Linux", "cloud computing", "AWS".
A typical article might have 5--10 tags applied.
Typically, tags will exhibit some correlation structure.
Posts about "cloud computing" are likely to mention "AWS"
and posts about "machine learning" are likely to mention "GPUs".

Sometimes such tagging problems
draw on enormous label sets.
The National Library of Medicine
employs many professional annotators
who associate each article to be indexed in PubMed
with a set of tags drawn from the
Medical Subject Headings (MeSH) ontology,
a collection of roughly 28,000 tags.
Correctly tagging articles is important
because it allows researchers to conduct
exhaustive reviews of the literature.
This is a time-consuming process and typically there is a one-year lag between archiving and tagging.
Machine learning can provide provisional tags
until each article has a proper manual review.
Indeed, for several years, the BioASQ organization
has [hosted competitions](http://bioasq.org/)
for this task.

#### Search

In the field of information retrieval,
we often impose ranks on sets of items.
Take web search for example.
The goal is less to determine *whether*
a particular page is relevant for a query,
but rather which, among a set of relevant results,
should be shown most prominently
to a particular user.
One way of doing this might be
to first assign a score
to every element in the set
and then to retrieve the top-rated elements.
[PageRank](https://en.wikipedia.org/wiki/PageRank),
the original secret sauce behind the Google search engine,
was an early example of such a scoring system.
Weirdly, the scoring provided by PageRank
did not depend on the actual query.
Instead, they relied on a simple relevance filter
to identify the set of relevant candidates
and then used PageRank to prioritize
the more authoritative pages.
Nowadays, search engines use machine learning and behavioral models
to obtain query-dependent relevance scores.
There are entire academic conferences devoted to this subject.

#### Recommender Systems

Recommender systems are another problem setting
that is related to search and ranking.
The problems are similar insofar as the goal
is to display a set of items relevant to the user.
The main difference is the emphasis on *personalization*
to specific users in the context of recommender systems.
For instance, for movie recommendations,
the results page for a science fiction fan
and the results page
for a connoisseur of Peter Sellers comedies
might differ significantly.
Similar problems pop up in other recommendation settings,
e.g., for retail products, music, and news recommendation.

In some cases, customers provide explicit feedback,
communicating how much they liked a particular product
(e.g., the product ratings and reviews
on Amazon, IMDb, or Goodreads).
In other cases, they provide implicit feedback,
e.g., by skipping titles on a playlist,
which might indicate
dissatisfaction or maybe just
indicate
that the song was inappropriate in context.
In the simplest formulations,
these systems are trained
to estimate some score,
such as an expected star rating
or the probability that a given user
will purchase a particular item.

Given such a model, for any given user,
we could retrieve the set of objects with the largest scores,
which could then be recommended to the user.
Production systems are considerably more advanced
and take detailed user activity and item characteristics
into account when computing such scores.
recommended by Amazon based on personalization algorithms
tuned to capture Aston's preferences.

Despite their tremendous economic value,
recommender systems
naively built on top of predictive models
suffer some serious conceptual flaws.
To start, we only observe *censored feedback*:
users preferentially rate movies
that they feel strongly about.
For example, on a five-point scale,
you might notice that items receive
many one- and five-star ratings
but that there are conspicuously few three-star ratings.
Moreover, current purchase habits are often a result
of the recommendation algorithm currently in place,
but learning algorithms do not always take this detail into account.
Thus it is possible for feedback loops to form
where a recommender system preferentially pushes an item
that is then taken to be better (due to greater purchases)
and in turn is recommended even more frequently.
Many of these problems---about
how to deal with censoring,
incentives, and feedback loops---are important open research questions.

#### Sequence Learning

So far, we have looked at problems where we have
some fixed number of inputs and produce a fixed number of outputs.
For example, we considered predicting house prices
given a fixed set of features:
square footage, number of bedrooms,
number of bathrooms, and the transit time to downtown.
We also discussed mapping from an image (of fixed dimension)
to the predicted probabilities that it belongs
to each among a fixed number of classes
and predicting star ratings associated with purchases
based on the user ID and product ID alone.
In these cases, once our model is trained,
after each test example is fed into our model,
it is immediately forgotten.
We assumed that successive observations were independent
and thus there was no need to hold on to this context.

But how should we deal with video snippets?
In this case, each snippet might consist of a different number of frames.
And our guess of what is going on in each frame might be much stronger
if we take into account the previous or succeeding frames.
The same goes for language.
For example, one popular deep learning problem is machine translation:
the task of ingesting sentences in some source language
and predicting their translations in another language.

Such problems also occur in medicine.
We might want a model to monitor patients in the intensive care unit
and to fire off alerts whenever their risk of dying in the next 24 hours
exceeds some threshold.
Here, we would not throw away everything
that we know about the patient history every hour,
because we might not want to make predictions based only
on the most recent measurements.

Questions like these are among the most
exciting applications of machine learning
and they are instances of *sequence learning*.
They require a model either to ingest sequences of inputs
or to emit sequences of outputs (or both).
Specifically, *sequence-to-sequence learning* considers problems
where both inputs and outputs consist of variable-length sequences.
Examples include machine translation
and speech-to-text transcription.
While it is impossible to consider
all types of sequence transformations,
the following special cases are worth mentioning.

**Tagging and Parsing**.
This involves annotating a text sequence with attributes.
Here, the inputs and outputs are *aligned*,
i.e., they are of the same number
and occur in a corresponding order.
For instance, in *part-of-speech (PoS) tagging*,
we annotate every word in a sentence
with the corresponding part of speech,
i.e., "noun" or "direct object".
Alternatively, we might want to know
which groups of contiguous words refer to named entities,
like *people*, *places*, or *organizations*.
In the cartoonishly simple example below,
we might just want to indicate whether or not any word in the sentence is part of a named entity (tagged as "Ent").

**Automatic Speech Recognition**.
With speech recognition, the input sequence
is an audio recording of a speaker (),
and the output is a transcript of what the speaker said.
The challenge is that there are many more audio frames
(sound is typically sampled at 8kHz or 16kHz)
than text, i.e., there is no 1:1 correspondence between audio and text,
since thousands of samples may
correspond to a single spoken word.
These are sequence-to-sequence learning problems,
where the output is much shorter than the input.
While humans are remarkably good at recognizing speech,
even from low-quality audio,
getting computers to perform the same feat
is a formidable challenge.

**Text to Speech**.
This is the inverse of automatic speech recognition.
Here, the input is text and the output is an audio file.
In this case, the output is much longer than the input.

**Machine Translation**.
Unlike the case of speech recognition,
where corresponding inputs and outputs
occur in the same order,
in machine translation,
unaligned data poses a new challenge.
Here the input and output sequences
can have different lengths,
and the corresponding regions
of the respective sequences
may appear in a different order.
Consider the following illustrative example
of the peculiar tendency of Germans
to place the verbs at the end of sentences:

Many related problems pop up in other learning tasks.
For instance, determining the order in which a user
reads a webpage is a two-dimensional layout analysis problem.
Dialogue problems exhibit all kinds of additional complications,
where determining what to say next requires taking into account
real-world knowledge and the prior state of the conversation
across long temporal distances.
Such topics are active areas of research.

### Unsupervised and Self-Supervised Learning

The previous examples focused on supervised learning,
where we feed the model a giant dataset
containing both the features and corresponding label values.
You could think of the supervised learner as having
an extremely specialized job and an extremely dictatorial boss.
The boss stands over the learner's shoulder and tells them exactly what to do
in every situation until they learn to map from situations to actions.
Working for such a boss sounds pretty lame.
On the other hand, pleasing such a boss is pretty easy.
You just recognize the pattern as quickly as possible
and imitate the boss's actions.

Considering the opposite situation,
it could be frustrating to work for a boss
who has no idea what they want you to do.
However, if you plan to be a data scientist,
you had better get used to it.
The boss might just hand you a giant dump of data
and tell you to *do some data science with it!*
This sounds vague because it is vague.
We call this class of problems *unsupervised learning*,
and the type and number of questions we can ask
is limited only by our creativity.
We will address unsupervised learning techniques
in later chapters.
To whet your appetite for now,
we describe a few of the following questions you might ask.

* Can we find a small number of prototypes
that accurately summarize the data?
Given a set of photos, can we group them into landscape photos,
pictures of dogs, babies, cats, and mountain peaks?
Likewise, given a collection of users' browsing activities,
can we group them into users with similar behavior?
This problem is typically known as *clustering*.
* Can we find a small number of parameters
that accurately capture the relevant properties of the data?
The trajectories of a ball are well described
by velocity, diameter, and mass of the ball.
Tailors have developed a small number of parameters
that describe human body shape fairly accurately
for the purpose of fitting clothes.
These problems are referred to as *subspace estimation*.
If the dependence is linear, it is called *principal component analysis*.
* Is there a representation of (arbitrarily structured) objects
in Euclidean space
such that symbolic properties can be well matched?
This can be used to describe entities and their relations,
such as "Rome" $-$ "Italy" $+$ "France" $=$ "Paris".
* Is there a description of the root causes
of much of the data that we observe?
For instance, if we have demographic data
about house prices, pollution, crime, location,
education, and salaries, can we discover
how they are related simply based on empirical data?
The fields concerned with *causality* and
*probabilistic graphical models* tackle such questions.
* Another important and exciting recent development in unsupervised learning
is the advent of *deep generative models*.
These models estimate the density of the data,
either explicitly or *implicitly*.
Once trained, we can use a generative model
either to score examples according to how likely they are,
or to sample synthetic examples from the learned distribution.
Early deep learning breakthroughs in generative modeling
came with the invention of *variational autoencoders*
and continued with the development of *generative adversarial networks* .
More recent advances include normalizing flows  and
diffusion models .

A further development in unsupervised learning
has been the rise of *self-supervised learning*,
techniques that leverage some aspect of the unlabeled data
to provide supervision.
For text, we can train models
to "fill in the blanks"
by predicting randomly masked words
using their surrounding words (contexts)
in big corpora without any labeling effort !
For images, we may train models
to tell the relative position
between two cropped regions
of the same image ,
to predict an occluded part of an image
based on the remaining portions of the image,
or to predict whether two examples
are perturbed versions of the same underlying image.
Self-supervised models often learn representations
that are subsequently leveraged
by fine-tuning the resulting models
on some downstream task of interest.

### Interacting with an Environment

So far, we have not discussed where data actually comes from,
or what actually happens when a machine learning model generates an output.
That is because supervised learning and unsupervised learning
do not address these issues in a very sophisticated way.
In each case, we grab a big pile of data upfront,
then set our pattern recognition machines in motion
without ever interacting with the environment again.
Because all the learning takes place
after the algorithm is disconnected from the environment,
this is sometimes called *offline learning*.
For example, supervised learning assumes
the simple interaction pattern
depicted in .

This simplicity of offline learning has its charms.
The upside is that we can worry
about pattern recognition in isolation,
with no concern about complications arising
from interactions with a dynamic environment.
But this problem formulation is limiting.
If you grew up reading Asimov's Robot novels,
then you probably picture artificially intelligent agents
capable not only of making predictions,
but also of taking actions in the world.
We want to think about intelligent *agents*,
not just predictive models.
This means that we need to think about choosing *actions*,
not just making predictions.
In contrast to mere predictions,
actions actually impact the environment.
If we want to train an intelligent agent,
we must account for the way its actions might
impact the future observations of the agent, and so offline learning is inappropriate.

Considering the interaction with an environment
opens a whole set of new modeling questions.
The following are just a few examples.

* Does the environment remember what we did previously?
* Does the environment want to help us, e.g., a user reading text into a speech recognizer?
* Does the environment want to beat us, e.g., spammers adapting their emails to evade spam filters?
* Does the environment have shifting dynamics? For example, would future data always resemble the past or would the patterns change over time, either naturally or in response to our automated tools?

These questions raise the problem of *distribution shift*,
where training and test data are different.
An example of this, that many of us may have met, is when taking exams written by a lecturer,
while the homework was composed by their teaching assistants.
Next, we briefly describe reinforcement learning,
a rich framework for posing learning problems in which
an agent interacts with an environment.

### Reinforcement Learning

If you are interested in using machine learning
to develop an agent that interacts with an environment
and takes actions, then you are probably going to wind up
focusing on *reinforcement learning*.
This might include applications to robotics,
to dialogue systems,
and even to developing artificial intelligence (AI)
for video games.
*Deep reinforcement learning*, which applies
deep learning to reinforcement learning problems,
has surged in popularity.
The breakthrough deep Q-network, that beat humans
at Atari games using only the visual input ,
and the AlphaGo program, which dethroned the world champion
at the board game Go ,
are two prominent examples.

Reinforcement learning gives a very general statement of a problem
in which an agent interacts with an environment over a series of time steps.
At each time step, the agent receives some *observation*
from the environment and must choose an *action*
that is subsequently transmitted back to the environment
via some mechanism (sometimes called an *actuator*), when, after each loop,
the agent receives a reward from the environment.
This process is illustrated in .
The agent then receives a subsequent observation,
and chooses a subsequent action, and so on.
The behavior of a reinforcement learning agent is governed by a *policy*.
In brief, a *policy* is just a function that maps
from observations of the environment to actions.
The goal of reinforcement learning is to produce good policies.

It is hard to overstate the generality
of the reinforcement learning framework.
For example, supervised learning
can be recast as reinforcement learning.
Say we had a classification problem.
We could create a reinforcement learning agent
with one action corresponding to each class.
We could then create an environment which gave a reward
that was exactly equal to the loss function
from the original supervised learning problem.

Further, reinforcement learning
can also address many problems
that supervised learning cannot.
For example, in supervised learning,
we always expect that the training input
comes associated with the correct label.
But in reinforcement learning,
we do not assume that, for each observation
the environment tells us the optimal action.
In general, we just get some reward.
Moreover, the environment may not even tell us
which actions led to the reward.

Consider the game of chess.
The only real reward signal comes at the end of the game
when we either win, earning a reward of, say, $1$,
or when we lose, receiving a reward of, say, $-1$.
So reinforcement learners must deal
with the *credit assignment* problem:
determining which actions to credit or blame for an outcome.
The same goes for an employee
who gets a promotion on October 11.
That promotion likely reflects a number
of well-chosen actions over the previous year.
Getting promoted in the future requires figuring out
which actions along the way led to the earlier promotions.

Reinforcement learners may also have to deal
with the problem of partial observability.
That is, the current observation might not
tell you everything about your current state.
Say your cleaning robot found itself trapped
in one of many identical closets in your house.
Rescuing the robot involves inferring
its precise location which might require considering earlier observations prior to it entering the closet.

Finally, at any given point, reinforcement learners
might know of one good policy,
but there might be many other better policies
that the agent has never tried.
The reinforcement learner must constantly choose
whether to *exploit* the best (currently) known strategy as a policy,
or to *explore* the space of strategies,
potentially giving up some short-term reward
in exchange for knowledge.

The general reinforcement learning problem
has a very general setting.
Actions affect subsequent observations.
Rewards are only observed when they correspond to the chosen actions.
The environment may be either fully or partially observed.
Accounting for all this complexity at once may be asking too much.
Moreover, not every practical problem exhibits all this complexity.
As a result, researchers have studied a number of
special cases of reinforcement learning problems.

When the environment is fully observed,
we call the reinforcement learning problem a *Markov decision process*.
When the state does not depend on the previous actions,
we call it a *contextual bandit problem*.
When there is no state, just a set of available actions
with initially unknown rewards, we have the classic *multi-armed bandit problem*.

## Roots

We have just reviewed a small subset of problems
that machine learning can address.
For a diverse set of machine learning problems,
deep learning provides powerful tools for their solution.
Although many deep learning methods are recent inventions,
the core ideas behind learning from data
have been studied for centuries.
In fact, humans have held the desire to analyze data
and to predict future outcomes for
ages, and it is this desire that is at the root of much of natural science and mathematics.
Two examples are the Bernoulli distribution, named after
[Jacob Bernoulli (1655--1705)](https://en.wikipedia.org/wiki/Jacob_Bernoulli),
and the Gaussian distribution discovered
by [Carl Friedrich Gauss (1777--1855)](https://en.wikipedia.org/wiki/Carl_Friedrich_Gauss).
Gauss invented, for instance, the least mean squares algorithm,
which is still used today for a multitude of problems
from insurance calculations to medical diagnostics.
Such tools enhanced the experimental approach
in the natural sciences---for instance, Ohm's law
relating current and voltage in a resistor
is perfectly described by a linear model.

Even in the middle ages, mathematicians
had a keen intuition of estimates.
For instance, the geometry book of [Jacob Köbel (1460--1533)](https://www.maa.org/press/periodicals/convergence/mathematical-treasures-jacob-kobels-geometry)
illustrates averaging the length of 16 adult men's feet
to estimate the typical foot length in the population ().

As a group of individuals exited a church,
16 adult men were asked to line up in a row
and have their feet measured.
The sum of these measurements was then divided by 16
to obtain an estimate for what now is called one foot.
This "algorithm" was later improved
to deal with misshapen feet;
The two men with the shortest and longest feet were sent away,
averaging only over the remainder.
This is among the earliest examples
of a trimmed mean estimate.

Statistics really took off with the availability and collection of data.
One of its pioneers, [Ronald Fisher (1890--1962)](https://en.wikipedia.org/wiki/Ronald_Fisher),
contributed significantly to its theory
and also its applications in genetics.
Many of his algorithms (such as linear discriminant analysis)
and concepts (such as the Fisher information matrix)
still hold a prominent place
in the foundations of modern statistics.
Even his data resources had a lasting impact.
The Iris dataset that Fisher released in 1936
is still sometimes used to demonstrate
machine learning algorithms.
Fisher was also a proponent of eugenics,
which should remind us that the morally dubious use of data science
has as long and enduring a history as its productive use
in industry and the natural sciences.

Other influences for machine learning
came from the information theory of
[Claude Shannon (1916--2001)](https://en.wikipedia.org/wiki/Claude_Shannon)
and the theory of computation proposed by
[Alan Turing (1912--1954)](https://en.wikipedia.org/wiki/Alan_Turing).
Turing posed the question "can machines think?”
in his famous paper *Computing Machinery and Intelligence* .
Describing what is now known as the Turing test, he proposed that a machine
can be considered *intelligent* if it is difficult
for a human evaluator to distinguish between the replies
from a machine and those of a human, based purely on textual interactions.

Further influences came from neuroscience and psychology.
After all, humans clearly exhibit intelligent behavior.
Many scholars have asked whether one could explain
and possibly reverse engineer this capacity.
One of the first biologically inspired algorithms
was formulated by [Donald Hebb (1904--1985)](https://en.wikipedia.org/wiki/Donald_O._Hebb).
In his groundbreaking book *The Organization of Behavior* ,
he posited that neurons learn by positive reinforcement.
This became known as the Hebbian learning rule.
These ideas inspired later work, such as
Rosenblatt's perceptron learning algorithm,
and laid the foundations of many stochastic gradient descent algorithms
that underpin deep learning today:
reinforce desirable behavior and diminish undesirable behavior
to obtain good settings of the parameters in a neural network.

Biological inspiration is what gave *neural networks* their name.
For over a century (dating back to the models of Alexander Bain, 1873,
and James Sherrington, 1890), researchers have tried to assemble
computational circuits that resemble networks of interacting neurons.
Over time, the interpretation of biology has become less literal,
but the name stuck. At its heart lie a few key principles
that can be found in most networks today:

* The alternation of linear and nonlinear processing units, often referred to as *layers*.
* The use of the chain rule (also known as *backpropagation*) for adjusting parameters in the entire network at once.

After initial rapid progress, research in neural networks
languished from around 1995 until 2005.
This was mainly due to two reasons.
First, training a network is computationally very expensive.
While random-access memory was plentiful at the end of the past century,
computational power was scarce.
Second, datasets were relatively small.
In fact, Fisher's Iris dataset from 1936
was still a popular tool for testing the efficacy of algorithms.
The MNIST dataset with its 60,000 handwritten digits was considered huge.

Given the scarcity of data and computation,
strong statistical tools such as kernel methods,
decision trees, and graphical models
proved empirically superior in many applications.
Moreover, unlike neural networks,
they did not require weeks to train
and provided predictable results
with strong theoretical guarantees.

## The Road to Deep Learning

Much of this changed with the availability
of massive amounts of data,
thanks to the World Wide Web,
the advent of companies serving
hundreds of millions of users online,
a dissemination of low-cost, high-quality sensors,
inexpensive data storage (Kryder's law),
and cheap computation (Moore's law).
In particular, the landscape of computation in deep learning
was revolutionized by advances in GPUs that were originally engineered for computer gaming.
Suddenly algorithms and models
that seemed computationally infeasible
were within reach.
This is best illustrated in .

:Dataset vs. computer memory and computational power

Note that random-access memory has not kept pace with the growth in data.
At the same time, increases in computational power
have outpaced the growth in datasets.
This means that statistical models
need to become more memory efficient,
and so they are free to spend more computer cycles
optimizing parameters, thanks to
the increased compute budget.
Consequently, the sweet spot in machine learning and statistics
moved from (generalized) linear models and kernel methods
to deep neural networks.
This is also one of the reasons why many of the mainstays
of deep learning, such as multilayer perceptrons
and Q-Learning ,
were essentially "rediscovered" in the past decade,
after lying comparatively dormant for considerable time.

The recent progress in statistical models, applications, and algorithms
has sometimes been likened to the Cambrian explosion:
a moment of rapid progress in the evolution of species.
Indeed, the state of the art is not just a mere consequence
of available resources applied to decades-old algorithms.
Note that the list of ideas below barely scratches the surface
of what has helped researchers achieve tremendous progress
over the past decade.

* Novel methods for capacity control, such as *dropout*
  have helped to mitigate overfitting.
  Here, noise is injected
  throughout the neural network during training.
* *Attention mechanisms* solved a second problem
  that had plagued statistics for over a century:
  how to increase the memory and complexity of a system without
  increasing the number of learnable parameters.
  Researchers found an elegant solution
  by using what can only be viewed as
  a *learnable pointer structure* .
  Rather than having to remember an entire text sequence, e.g.,
  for machine translation in a fixed-dimensional representation,
  all that needed to be stored was a pointer to the intermediate state
  of the translation process. This allowed for significantly
  increased accuracy for long sequences, since the model
  no longer needed to remember the entire sequence before
  commencing the generation of a new one.
* Built solely on attention mechanisms,
  the *Transformer* architecture  has demonstrated superior *scaling* behavior: it performs better with an increase in dataset size, model size, and amount of training compute . This architecture has demonstrated compelling success in a wide range of areas,
  such as natural language processing , computer vision , speech recognition , reinforcement learning , and graph neural networks . For example, a single Transformer pretrained on modalities
  as diverse as text, images, joint torques, and button presses
  can play Atari, caption images, chat,
  and control a robot .
* Modeling probabilities of text sequences, *language models* can predict text given other text. Scaling up the data, model, and compute has unlocked a growing number of capabilities of language models to perform desired tasks via human-like text generation based on input text . For instance, aligning language models with human intent , OpenAI's [ChatGPT](https://chat.openai.com/) allows users to interact with it in a conversational way to solve problems, such as code debugging and creative writing.
* Multi-stage designs, e.g., via the memory networks
  and the neural programmer-interpreter
  permitted statistical modelers to describe iterative approaches to reasoning.
  These tools allow for an internal state of the deep neural network
  to be modified repeatedly,
  thus carrying out subsequent steps
  in a chain of reasoning, just as a processor
  can modify memory for a computation.
* A key development in *deep generative modeling* was the invention
  of *generative adversarial networks*
  Traditionally, statistical methods for density estimation
  and generative models focused on finding proper probability distributions
  and (often approximate) algorithms for sampling from them.
  As a result, these algorithms were largely limited by the lack of
  flexibility inherent in the statistical models.
  The crucial innovation in generative adversarial networks was to replace the sampler
  by an arbitrary algorithm with differentiable parameters.
  These are then adjusted in such a way that the discriminator
  (effectively a two-sample test) cannot distinguish fake from real data.
  Through the ability to use arbitrary algorithms to generate data,
  density estimation was opened up to a wide variety of techniques.
  Examples of galloping zebras
  and of fake celebrity faces
  are each testimony to this progress.
  Even amateur doodlers can produce
  photorealistic images just based on sketches describing the layout of a scene .
* Furthermore, while the diffusion process gradually adds random noise to data samples, *diffusion models*  learn the denoising process to gradually construct data samples from random noise, reversing the diffusion process. They have started to replace generative adversarial networks in more recent deep generative models, such as in DALL-E 2  and Imagen  for creative art and image generation based on text descriptions.
* In many cases, a single GPU is insufficient for processing the large amounts of data available for training.
  Over the past decade the ability to build parallel and
  distributed training algorithms has improved significantly.
  One of the key challenges in designing scalable algorithms
  is that the workhorse of deep learning optimization,
  stochastic gradient descent, relies on relatively
  small minibatches of data to be processed.
  At the same time, small batches limit the efficiency of GPUs.
  Hence, training on 1,024 GPUs with a minibatch size of,
  say, 32 images per batch amounts to an aggregate minibatch
  of about 32,000 images. Work, first by
  and subsequently by
  and  pushed the size up to 64,000 observations,
  reducing training time for the ResNet-50 model
  on the ImageNet dataset to less than 7 minutes.
  By comparison, training times were initially of the order of days.
* The ability to parallelize computation
  has also contributed to progress in *reinforcement learning*.
  This has led to significant progress in computers achieving
  superhuman performance on tasks like Go, Atari games,
  Starcraft, and in physics simulations (e.g., using MuJoCo)
  where environment simulators are available.
  See, e.g.,  for a description
  of such achievements in AlphaGo. In a nutshell,
  reinforcement learning works best
  if plenty of (state, action, reward) tuples are available.
  Simulation provides such an avenue.
* Deep learning frameworks have played a crucial role
  in disseminating ideas.
  The first generation of open-source frameworks
  for neural network modeling consisted of
  [Caffe](https://github.com/BVLC/caffe),
  [Torch](https://github.com/torch), and
  [Theano](https://github.com/Theano/Theano).
  Many seminal papers were written using these tools.
  These have now been superseded by
  [TensorFlow](https://github.com/tensorflow/tensorflow) (often used via its high-level API [Keras](https://github.com/keras-team/keras)), [CNTK](https://github.com/Microsoft/CNTK), [Caffe 2](https://github.com/caffe2/caffe2), and [Apache MXNet](https://github.com/apache/incubator-mxnet).
  The third generation of frameworks consists
  of so-called *imperative* tools for deep learning,
  a trend that was arguably ignited by [Chainer](https://github.com/chainer/chainer),
  which used a syntax similar to Python NumPy to describe models.
  This idea was adopted by both [PyTorch](https://github.com/pytorch/pytorch),
  the [Gluon API](https://github.com/apache/incubator-mxnet) of MXNet,
  and [JAX](https://github.com/google/jax).

The division of labor between system researchers building better tools
and statistical modelers building better neural networks
has greatly simplified things. For instance,
training a linear logistic regression model
used to be a nontrivial homework problem,
worthy to give to new machine learning
Ph.D. students at Carnegie Mellon University in 2014.
By now, this task can be accomplished
with under 10 lines of code,
putting it firmly within the reach of any programmer.

## Success Stories

Artificial intelligence has a long history of delivering results
that would be difficult to accomplish otherwise.
For instance, mail sorting systems
using optical character recognition
have been deployed since the 1990s.
This is, after all, the source
of the famous MNIST dataset
of handwritten digits.
The same applies to reading checks for bank deposits and scoring
creditworthiness of applicants.
Financial transactions are checked for fraud automatically.
This forms the backbone of many e-commerce payment systems,
such as PayPal, Stripe, AliPay, WeChat, Apple, Visa, and MasterCard.
Computer programs for chess have been competitive for decades.
Machine learning feeds search, recommendation, personalization,
and ranking on the Internet.
In other words, machine learning is pervasive, albeit often hidden from sight.

It is only recently that AI
has been in the limelight, mostly due to
solutions to problems
that were considered intractable previously
and that are directly related to consumers.
Many of such advances are attributed to deep learning.

* Intelligent assistants, such as Apple's Siri,
  Amazon's Alexa, and Google's assistant,
  are able to respond to spoken requests
  with a reasonable degree of accuracy.
  This includes menial jobs, like turning on light switches,
  and more complex tasks, such as arranging barber's appointments
  and offering phone support dialog.
  This is likely the most noticeable sign
  that AI is affecting our lives.
* A key ingredient in digital assistants
  is their ability to recognize speech accurately.
  The accuracy of such systems has gradually
  increased to the point
  of achieving parity with humans
  for certain applications .
* Object recognition has likewise come a long way.
  Identifying the object in a picture
  was a fairly challenging task in 2010.
  On the ImageNet benchmark researchers from NEC Labs
  and University of Illinois at Urbana-Champaign
  achieved a top-five error rate of 28% .
  By 2017, this error rate was reduced to 2.25% .
  Similarly, stunning results have been achieved
  for identifying birdsong and for diagnosing skin cancer.
* Prowess in games used to provide
  a measuring stick for human ability.
  Starting from TD-Gammon, a program for playing backgammon
  using temporal difference reinforcement learning,
  algorithmic and computational progress
  has led to algorithms for a wide range of applications.
  Compared with backgammon, chess has
  a much more complex state space and set of actions.
  DeepBlue beat Garry Kasparov using massive parallelism,
  special-purpose hardware and efficient search
  through the game tree .
  Go is more difficult still, due to its huge state space.
  AlphaGo reached human parity in 2015,
  using deep learning combined with Monte Carlo tree sampling .
  The challenge in Poker was that the state space is large
  and only partially observed
  (we do not know the opponents' cards).
  Libratus exceeded human performance in Poker
  using efficiently structured strategies .
* Another indication of progress in AI
  is the advent of self-driving vehicles.
  While full autonomy is not yet within reach,
  excellent progress has been made in this direction,
  with companies such as Tesla, NVIDIA,
  and Waymo shipping products
  that enable partial autonomy.
  What makes full autonomy so challenging
  is that proper driving requires
  the ability to perceive, to reason
  and to incorporate rules into a system.
  At present, deep learning is used primarily
  in the visual aspect of these problems.
  The rest is heavily tuned by engineers.

This barely scratches the surface
of significant applications of machine learning.
For instance, robotics, logistics, computational biology,
particle physics, and astronomy
owe some of their most impressive recent advances
at least in parts to machine learning, which is thus becoming
a ubiquitous tool for engineers and scientists.

Frequently, questions about a coming AI apocalypse
and the plausibility of a *singularity*
have been raised in non-technical articles.
The fear is that somehow machine learning systems
will become sentient and make decisions,
independently of their programmers,
that directly impact the lives of humans.
To some extent, AI already affects
the livelihood of humans in direct ways:
creditworthiness is assessed automatically,
autopilots mostly navigate vehicles, decisions about
whether to grant bail use statistical data as input.
More frivolously, we can ask Alexa to switch on the coffee machine.

Fortunately, we are far from a sentient AI system
that could deliberately manipulate its human creators.
First, AI systems are engineered,
trained, and deployed
in a specific, goal-oriented manner.
While their behavior might give the illusion
of general intelligence, it is a combination of rules, heuristics
and statistical models that underlie the design.
Second, at present, there are simply no tools for *artificial general intelligence*
that are able to improve themselves,
reason about themselves, and that are able to modify,
extend, and improve their own architecture
while trying to solve general tasks.

A much more pressing concern is how AI is being used in our daily lives.
It is likely that many routine tasks, currently fulfilled by humans, can and will be automated.
Farm robots will likely reduce the costs for organic farmers
but they will also automate harvesting operations.
This phase of the industrial revolution
may have profound consequences for large swaths of society,
since menial jobs provide much employment
in many countries.
Furthermore, statistical models, when applied without care,
can lead to racial, gender, or age bias and raise
reasonable concerns about procedural fairness
if automated to drive consequential decisions.
It is important to ensure that these algorithms are used with care.
With what we know today, this strikes us as a much more pressing concern
than the potential of malevolent superintelligence for destroying humanity.

## The Essence of Deep Learning

Thus far, we have talked in broad terms about machine learning.
Deep learning is the subset of machine learning
concerned with models based on many-layered neural networks.
It is *deep* in precisely the sense that its models
learn many *layers* of transformations.
While this might sound narrow,
deep learning has given rise
to a dizzying array of models, techniques,
problem formulations, and applications.
Many intuitions have been developed
to explain the benefits of depth.
Arguably, all machine learning
has many layers of computation,
the first consisting of feature processing steps.
What differentiates deep learning is that
the operations learned at each of the many layers
of representations are learned jointly from data.

The problems that we have discussed so far,
such as learning from the raw audio signal,
the raw pixel values of images,
or mapping between sentences of arbitrary lengths and
their counterparts in foreign languages,
are those where deep learning excels
and traditional methods falter.
It turns out that these many-layered models
are capable of addressing low-level perceptual data
in a way that previous tools could not.
Arguably the most significant commonality
in deep learning methods is *end-to-end training*.
That is, rather than assembling a system
based on components that are individually tuned,
one builds the system and then tunes their performance jointly.
For instance, in computer vision scientists
used to separate the process of *feature engineering*
from the process of building machine learning models.
The Canny edge detector
and Lowe's SIFT feature extractor
reigned supreme for over a decade as algorithms
for mapping images into feature vectors.
In bygone days, the crucial part of applying machine learning to these problems
consisted of coming up with manually-engineered ways
of transforming the data into some form amenable to shallow models.
Unfortunately, there is only so much that humans can accomplish
by ingenuity in comparison with a consistent evaluation
over millions of choices carried out automatically by an algorithm.
When deep learning took over,
these feature extractors were replaced
by automatically tuned filters that yielded superior accuracy.

Thus, one key advantage of deep learning is that it replaces
not only the shallow models at the end of traditional learning pipelines,
but also the labor-intensive process of feature engineering.
Moreover, by replacing much of the domain-specific preprocessing,
deep learning has eliminated many of the boundaries
that previously separated computer vision, speech recognition,
natural language processing, medical informatics, and other application areas,
thereby offering a unified set of tools for tackling diverse problems.

Beyond end-to-end training, we are experiencing a transition
from parametric statistical descriptions to fully nonparametric models.
When data is scarce, one needs to rely on simplifying assumptions about reality
in order to obtain useful models.
When data is abundant, these can be replaced
by nonparametric models that better fit the data.
To some extent, this mirrors the progress
that physics experienced in the middle of the previous century
with the availability of computers.
Rather than solving by hand parametric approximations of how electrons behave,
one can now resort to numerical simulations of the associated partial differential equations.
This has led to much more accurate models,
albeit often at the expense of interpretation.

Another difference from previous work is the acceptance of suboptimal solutions,
dealing with nonconvex nonlinear optimization problems,
and the willingness to try things before proving them.
This new-found empiricism in dealing with statistical problems,
combined with a rapid influx of talent has led
to rapid progress in the development of practical algorithms,
albeit in many cases at the expense of modifying
and re-inventing tools that existed for decades.

In the end, the deep learning community prides itself
on sharing tools across academic and corporate boundaries,
releasing many excellent libraries, statistical models,
and trained networks as open source.
It is in this spirit that the notebooks forming this book
are freely available for distribution and use.
We have worked hard to lower the barriers of access
for anyone wishing to learn about deep learning
and we hope that our readers will benefit from this.

## Summary

Machine learning studies how computer systems
can leverage experience (often data)
to improve performance at specific tasks.
It combines ideas from statistics, data mining, and optimization.
Often, it is used as a means of implementing AI solutions.
As a class of machine learning, representational learning
focuses on how to automatically find
the appropriate way to represent data.
Considered as multi-level representation learning
through learning many layers of transformations,
deep learning replaces not only the shallow models
at the end of traditional machine learning pipelines,
but also the labor-intensive process of feature engineering.
Much of the recent progress in deep learning
has been triggered by an abundance of data
arising from cheap sensors and Internet-scale applications,
and by significant progress in computation, mostly through GPUs.
Furthermore, the availability of efficient deep learning frameworks
has made design and implementation of whole system optimization significantly easier,
and this is a key component in obtaining high performance.

## Exercises

1. Which parts of code that you are currently writing could be "learned",
   i.e., improved by learning and automatically determining design choices
   that are made in your code?
   Does your code include heuristic design choices?
   What data might you need to learn the desired behavior?
1. Which problems that you encounter have many examples for their solution,
   yet no specific way for automating them?
   These may be prime candidates for using deep learning.
1. Describe the relationships between algorithms, data, and computation. How do characteristics of the data and the current available computational resources influence the appropriateness of various algorithms?
1. Name some settings where end-to-end training is not currently the default approach but where it might be useful.

[Discussions](https://discuss.d2l.ai/t/22)

# Linear Neural Networks for Regression

Before we worry about making our neural networks deep,
it will be helpful to implement some shallow ones,
for which the inputs connect directly to the outputs.
This will prove important for a few reasons.
First, rather than getting distracted by complicated architectures,
we can focus on the basics of neural network training,
including parametrizing the output layer, handling data,
specifying a loss function, and training the model.
Second, this class of shallow networks happens
to comprise the set of linear models,
which subsumes many classical methods of statistical prediction,
including linear and softmax regression.
Understanding these classical tools is pivotal
because they are widely used in many contexts
and we will often need to use them as baselines
when justifying the use of fancier architectures.
This chapter will focus narrowly on linear regression
and the next one will extend our modeling repertoire
by developing linear neural networks for classification.

## Linear Regression

*Regression* problems pop up whenever we want to predict a numerical value.
Common examples include predicting prices (of homes, stocks, etc.),
predicting the length of stay (for patients in the hospital),
forecasting demand (for retail sales), among numerous others.
Not every prediction problem is one of classical regression.
Later on, we will introduce classification problems,
where the goal is to predict membership among a set of categories.

As a running example, suppose that we wish
to estimate the prices of houses (in dollars)
based on their area (in square feet) and age (in years).
To develop a model for predicting house prices,
we need to get our hands on data,
including the sales price, area, and age for each home.
In the terminology of machine learning,
the dataset is called a *training dataset* or *training set*,
and each row (containing the data corresponding to one sale)
is called an *example* (or *data point*, *instance*, *sample*).
The thing we are trying to predict (price)
is called a *label* (or *target*).
The variables (age and area)
upon which the predictions are based
are called *features* (or *covariates*).

### Basics

*Linear regression* is both the simplest
and most popular among the standard tools
for tackling regression problems.
Dating back to the dawn of the 19th century ,
linear regression flows from a few simple assumptions.
First, we assume that the relationship
between features $\mathbf{x}$ and target $y$
is approximately linear,
i.e., that the conditional mean $E[Y \mid X=\mathbf{x}]$
can be expressed as a weighted sum
of the features $\mathbf{x}$.
This setup allows that the target value
may still deviate from its expected value
on account of observation noise.
Next, we can impose the assumption that any such noise
is well behaved, following a Gaussian distribution.
Typically, we will use $n$ to denote
the number of examples in our dataset.
We use superscripts to enumerate samples and targets,
and subscripts to index coordinates.
More concretely,
$\mathbf{x}^{(i)}$ denotes the $i^{\textrm{th}}$ sample
and $x_j^{(i)}$ denotes its $j^{\textrm{th}}$ coordinate.

#### Model

At the heart of every solution is a model
that describes how features can be transformed
into an estimate of the target.
The assumption of linearity means that
the expected value of the target (price) can be expressed
as a weighted sum of the features (area and age):

Collecting all features into a vector $\mathbf{x} \in \mathbb{R}^d$
and all weights into a vector $\mathbf{w} \in \mathbb{R}^d$,
we can express our model compactly via the dot product
between $\mathbf{w}$ and $\mathbf{x}$:

where broadcasting () is applied during the summation.
Given features of a training dataset $\mathbf{X}$
and corresponding (known) labels $\mathbf{y}$,
the goal of linear regression is to find
the weight vector $\mathbf{w}$ and the bias term $b$
such that, given features of a new data example
sampled from the same distribution as $\mathbf{X}$,
the new example's label will (in expectation)
be predicted with the smallest error.

Even if we believe that the best model for
predicting $y$ given $\mathbf{x}$ is linear,
we would not expect to find a real-world dataset of $n$ examples where
$y^{(i)}$ exactly equals $\mathbf{w}^\top \mathbf{x}^{(i)}+b$
for all $1 \leq i \leq n$.
For example, whatever instruments we use to observe
the features $\mathbf{X}$ and labels $\mathbf{y}$, there might be a small amount of measurement error.
Thus, even when we are confident
that the underlying relationship is linear,
we will incorporate a noise term to account for such errors.

Before we can go about searching for the best *parameters*
(or *model parameters*) $\mathbf{w}$ and $b$,
we will need two more things:
(i) a measure of the quality of some given model;
and (ii) a procedure for updating the model to improve its quality.

#### Loss Function

Naturally, fitting our model to the data requires
that we agree on some measure of *fitness*
(or, equivalently, of *unfitness*).
*Loss functions* quantify the distance
between the *real* and *predicted* values of the target.
The loss will usually be a nonnegative number
where smaller values are better
and perfect predictions incur a loss of 0.
For regression problems, the most common loss function is the squared error.
When our prediction for an example $i$ is $\hat{y}^{(i)}$
and the corresponding true label is $y^{(i)}$,
the *squared error* is given by:

When training the model, we seek parameters ($\mathbf{w}^*, b^*$)
that minimize the total loss across all training examples:

    \partial_{\mathbf{w}} \|\mathbf{y} - \mathbf{X}\mathbf{w}\|^2 =
    2 \mathbf{X}^\top (\mathbf{X} \mathbf{w} - \mathbf{y}) = 0
    \textrm{ and hence }
    \mathbf{X}^\top \mathbf{y} = \mathbf{X}^\top \mathbf{X} \mathbf{w}.
\end{aligned}$$

Solving for $\mathbf{w}$ provides us with the optimal solution
for the optimization problem.
Note that this solution

In summary, minibatch SGD proceeds as follows:
(i) initialize the values of the model parameters, typically at random;
(ii) iteratively sample random minibatches from the data,
updating the parameters in the direction of the negative gradient.
For quadratic losses and affine transformations,
this has a closed-form expansion:

Below [**we define a function to compute the normal distribution**].

We can now (**visualize the normal distributions**).

Note that changing the mean corresponds
to a shift along the $x$-axis,
and increasing the variance
spreads the distribution out,
lowering its peak.

One way to motivate linear regression with squared loss
is to assume that observations arise from noisy measurements,
where the noise $\epsilon$ follows the normal distribution
$\mathcal{N}(0, \sigma^2)$:

As such, the likelihood factorizes.
According to *the principle of maximum likelihood*,
the best values of parameters $\mathbf{w}$ and $b$ are those
that maximize the *likelihood* of the entire dataset:

If we assume that $\sigma$ is fixed,
we can ignore the first term,
because it does not depend on $\mathbf{w}$ or $b$.
The second term is identical
to the squared error loss introduced earlier,
except for the multiplicative constant $\frac{1}{\sigma^2}$.
Fortunately, the solution does not depend on $\sigma$ either.
It follows that minimizing the mean squared error
is equivalent to the maximum likelihood estimation
of a linear model under the assumption of additive Gaussian noise.

### Linear Regression as a Neural Network

While linear models are not sufficiently rich
to express the many complicated networks
that we will introduce in this book,
(artificial) neural networks are rich enough
to subsume linear models as networks
in which every feature is represented by an input neuron,
all of which are connected directly to the output.

linear regression as a neural network.
The diagram highlights the connectivity pattern,
such as how each input is connected to the output,
but not the specific values taken by the weights or biases.

The inputs are $x_1, \ldots, x_d$.
We refer to $d$ as the *number of inputs*
or the *feature dimensionality* in the input layer.
The output of the network is $o_1$.
Because we are just trying to predict
a single numerical value,
we have only one output neuron.
Note that the input values are all *given*.
There is just a single *computed* neuron.
In summary, we can think of linear regression
as a single-layer fully connected neural network.
We will encounter networks
with far more layers
in later chapters.

#### Biology

Because linear regression predates computational neuroscience,
it might seem anachronistic to describe
linear regression in terms of neural networks.
Nonetheless, they were a natural place to start
when the cyberneticists and neurophysiologists
Warren McCulloch and Walter Pitts began to develop
models of artificial neurons.
Consider the cartoonish picture
of a biological neuron in ,
consisting of *dendrites* (input terminals),
the *nucleus* (CPU), the *axon* (output wire),
and the *axon terminals* (output terminals),
enabling connections to other neurons via *synapses*.

Information $x_i$ arriving from other neurons
(or environmental sensors) is received in the dendrites.
In particular, that information is weighted
by *synaptic weights* $w_i$,
determining the effect of the inputs,
e.g., activation or inhibition via the product $x_i w_i$.
The weighted inputs arriving from multiple sources
are aggregated in the nucleus
as a weighted sum $y = \sum_i x_i w_i + b$,
possibly subject to some nonlinear postprocessing via a function $\sigma(y)$.
This information is then sent via the axon to the axon terminals,
where it reaches its destination
(e.g., an actuator such as a muscle)
or it is fed into another neuron via its dendrites.

Certainly, the high-level idea that many such units
could be combined, provided they have the correct connectivity and learning algorithm,
to produce far more interesting and complex behavior
than any one neuron alone could express
arises from our study of real biological neural systems.
At the same time, most research in deep learning today
draws inspiration from a much wider source.
We invoke
who pointed out that although airplanes might have been *inspired* by birds,
ornithology has not been the primary driver
of aeronautics innovation for some centuries.
Likewise, inspiration in deep learning these days
comes in equal or greater measure
from mathematics, linguistics, psychology,
statistics, computer science, and many other fields.

### Summary

In this section, we introduced
traditional linear regression,
where the parameters of a linear function
are chosen to minimize squared loss on the training set.
We also motivated this choice of objective
both via some practical considerations
and through an interpretation
of linear regression as maximimum likelihood estimation
under an assumption of linearity and Gaussian noise.
After discussing both computational considerations
and connections to statistics,
we showed how such linear models could be expressed
as simple neural networks where the inputs
are directly wired to the output(s).
While we will soon move past linear models altogether,
they are sufficient to introduce most of the components
that all of our models require:
parametric forms, differentiable objectives,
optimization via minibatch stochastic gradient descent,
and ultimately, evaluation on previously unseen data.

### Exercises

1. Assume that we have some data $x_1, \ldots, x_n \in \mathbb{R}$. Our goal is to find a constant $b$ such that $\sum_i (x_i - b)^2$ is minimized.
    1. Find an analytic solution for the optimal value of $b$.
    1. How does this problem and its solution relate to the normal distribution?
    1. What if we change the loss from $\sum_i (x_i - b)^2$ to $\sum_i |x_i-b|$? Can you find the optimal solution for $b$?
1. Prove that the affine functions that can be expressed by $\mathbf{x}^\top \mathbf{w} + b$ are equivalent to linear functions on $(\mathbf{x}, 1)$.
1. Assume that you want to find quadratic functions of $\mathbf{x}$, i.e., $f(\mathbf{x}) = b + \sum_i w_i x_i + \sum_{j \leq i} w_{ij} x_{i} x_{j}$. How would you formulate this in a deep network?
1. Recall that one of the conditions for the linear regression problem to be solvable was that the design matrix $\mathbf{X}^\top \mathbf{X}$ has full rank.
    1. What happens if this is not the case?
    1. How could you fix it? What happens if you add a small amount of coordinate-wise independent Gaussian noise to all entries of $\mathbf{X}$?
    1. What is the expected value of the design matrix $\mathbf{X}^\top \mathbf{X}$ in this case?
    1. What happens with stochastic gradient descent when $\mathbf{X}^\top \mathbf{X}$ does not have full rank?
1. Assume that the noise model governing the additive noise $\epsilon$ is the exponential distribution. That is, $p(\epsilon) = \frac{1}{2} \exp(-|\epsilon|)$.
    1. Write out the negative log-likelihood of the data under the model $-\log P(\mathbf y \mid \mathbf X)$.
    1. Can you find a closed form solution?
    1. Suggest a minibatch stochastic gradient descent algorithm to solve this problem. What could possibly go wrong (hint: what happens near the stationary point as we keep on updating the parameters)? Can you fix this?
1. Assume that we want to design a neural network with two layers by composing two linear layers. That is, the output of the first layer becomes the input of the second layer. Why would such a naive composition not work?
1. What happens if you want to use regression for realistic price estimation of houses or stock prices?
    1. Show that the additive Gaussian noise assumption is not appropriate. Hint: can we have negative prices? What about fluctuations?
    1. Why would regression to the logarithm of the price be much better, i.e., $y = \log \textrm{price}$?
    1. What do you need to worry about when dealing with pennystock, i.e., stock with very low prices? Hint: can you trade at all possible prices? Why is this a bigger problem for cheap stock? For more information review the celebrated Black--Scholes model for option pricing .
1. Suppose we want to use regression to estimate the *number* of apples sold in a grocery store.
    1. What are the problems with a Gaussian additive noise model? Hint: you are selling apples, not oil.
    1. The [Poisson distribution](https://en.wikipedia.org/wiki/Poisson_distribution) captures distributions over counts. It is given by $p(k \mid \lambda) = \lambda^k e^{-\lambda}/k!$. Here $\lambda$ is the rate function and $k$ is the number of events you see. Prove that $\lambda$ is the expected value of counts $k$.
    1. Design a loss function associated with the Poisson distribution.
    1. Design a loss function for estimating $\log \lambda$ instead.

[Discussions](https://discuss.d2l.ai/t/40)

[Discussions](https://discuss.d2l.ai/t/258)

[Discussions](https://discuss.d2l.ai/t/259)

## Generalization

Consider two college students diligently
preparing for their final exam.
Commonly, this preparation will consist
of practicing and testing their abilities
by taking exams administered in previous years.
Nonetheless, doing well on past exams is no guarantee
that they will excel when it matters.
For instance, imagine a student, Extraordinary Ellie,
whose preparation consisted entirely
of memorizing the answers
to previous years' exam questions.
Even if Ellie were endowed
with an extraordinary memory,
and thus could perfectly recall the answer
to any *previously seen* question,
she might nevertheless freeze
when faced with a new (*previously unseen*) question.
By comparison, imagine another student,
Inductive Irene, with comparably poor
memorization skills,
but a knack for picking up patterns.
Note that if the exam truly consisted of
recycled questions from a previous year,
Ellie would handily outperform Irene.
Even if Irene's inferred patterns
yielded 90% accurate predictions,
they could never compete with
Ellie's 100% recall.
However, even if the exam consisted
entirely of fresh questions,
Irene might maintain her 90% average.

As machine learning scientists,
our goal is to discover *patterns*.
But how can we be sure that we have
truly discovered a *general* pattern
and not simply memorized our data?
Most of the time, our predictions are only useful
if our model discovers such a pattern.
We do not want to predict yesterday's stock prices, but tomorrow's.
We do not need to recognize
already diagnosed diseases
for previously seen patients,
but rather previously undiagnosed
ailments in previously unseen patients.
This problem---how to discover patterns that *generalize*---is
the fundamental problem of machine learning,
and arguably of all of statistics.
We might cast this problem as just one slice
of a far grander question
that engulfs all of science:
when are we ever justified
in making the leap from particular observations
to more general statements?

In real life, we must fit our models
using a finite collection of data.
The typical scales of that data
vary wildly across domains.
For many important medical problems,
we can only access a few thousand data points.
When studying rare diseases,
we might be lucky to access hundreds.
By contrast, the largest public datasets
consisting of labeled photographs,
e.g., ImageNet ,
contain millions of images.
And some unlabeled image collections
such as the Flickr YFC100M dataset
can be even larger, containing
over 100 million images .
However, even at this extreme scale,
the number of available data points
remains infinitesimally small
compared to the space of all possible images
at a megapixel resolution.
Whenever we work with finite samples,
we must keep in mind the risk
that we might fit our training data,
only to discover that we failed
to discover a generalizable pattern.

The phenomenon of fitting closer to our training data
than to the underlying distribution is called *overfitting*,
and techniques for combatting overfitting
are often called *regularization* methods.
While it is no substitute for a proper introduction
to statistical learning theory (see ),
we will give you just enough intuition to get going.
We will revisit generalization in many chapters
throughout the book,
exploring both what is known about
the principles underlying generalization
in various models,
and also heuristic techniques
that have been found (empirically)
to yield improved generalization
on tasks of practical interest.

### Training Error and Generalization Error

In the standard supervised learning setting,
we assume that the training data and the test data
are drawn *independently* from *identical* distributions.
This is commonly called the *IID assumption*.
While this assumption is strong,
it is worth noting that, absent any such assumption,
we would be dead in the water.
Why should we believe that training data
sampled from distribution $P(X,Y)$
should tell us how to make predictions on
test data generated by a *different distribution* $Q(X,Y)$?
Making such leaps turns out to require
strong assumptions about how $P$ and $Q$ are related.
Later on we will discuss some assumptions
that allow for shifts in distribution
but first we need to understand the IID case,
where $P(\cdot) = Q(\cdot)$.

To begin with, we need to differentiate between
the *training error* $R_\textrm{emp}$,
which is a *statistic*
calculated on the training dataset,
and the *generalization error* $R$,
which is an *expectation* taken
with respect to the underlying distribution.
You can think of the generalization error as
what you would see  if you applied your model
to an infinite stream of additional data examples
drawn from the same underlying data distribution.
Formally the training error is expressed as a *sum* (with the same notation as ):

\int \int l(\mathbf{x}, y, f(\mathbf{x})) p(\mathbf{x}, y) \;d\mathbf{x} dy.$$

Problematically, we can never calculate
the generalization error $R$ exactly.
Nobody ever tells us the precise form
of the density function $p(\mathbf{x}, y)$.
Moreover, we cannot sample an infinite stream of data points.
Thus, in practice, we must *estimate* the generalization error
by applying our model to an independent test set
constituted of a random selection of examples
$\mathbf{X}'$ and labels $\mathbf{y}'$
that were withheld from our training set.
This consists of applying the same formula
that was used for calculating the empirical training error
but to a test set $\mathbf{X}', \mathbf{y}'$.

Crucially, when we evaluate our classifier on the test set,
we are working with a *fixed* classifier
(it does not depend on the sample of the test set),
and thus estimating its error
is simply the problem of mean estimation.
However the same cannot be said
for the training set.
Note that the model we wind up with
depends explicitly on the selection of the training set
and thus the training error will in general
be a biased estimate of the true error
on the underlying population.
The central question of generalization
is then when should we expect our training error
to be close to the population error
(and thus the generalization error).

#### Model Complexity

In classical theory, when we have
simple models and abundant data,
the training and generalization errors tend to be close.
However, when we work with
more complex models and/or fewer examples,
we expect the training error to go down
but the generalization gap to grow.
This should not be surprising.
Imagine a model class so expressive that
for any dataset of $n$ examples,
we can find a set of parameters
that can perfectly fit arbitrary labels,
even if randomly assigned.
In this case, even if we fit our training data perfectly,
how can we conclude anything about the generalization error?
For all we know, our generalization error
might be no better than random guessing.

In general, absent any restriction on our model class,
we cannot conclude, based on fitting the training data alone,
that our model has discovered any generalizable pattern .
On the other hand, if our model class
was not capable of fitting arbitrary labels,
then it must have discovered a pattern.
Learning-theoretic ideas about model complexity
derived some inspiration from the ideas
of Karl Popper, an influential philosopher of science,
who formalized the criterion of falsifiability.
According to Popper, a theory
that can explain any and all observations
is not a scientific theory at all!
After all, what has it told us about the world
if it has not ruled out any possibility?
In short, what we want is a hypothesis
that *could not* explain any observations
we might conceivably make
and yet nevertheless happens to be compatible
with those observations that we *in fact* make.

Now what precisely constitutes an appropriate
notion of model complexity is a complex matter.
Often, models with more parameters
are able to fit a greater number
of arbitrarily assigned labels.
However, this is not necessarily true.
For instance, kernel methods operate in spaces
with infinite numbers of parameters,
yet their complexity is controlled
by other means .
One notion of complexity that often proves useful
is the range of values that the parameters can take.
Here, a model whose parameters are permitted
to take arbitrary values
would be more complex.
We will revisit this idea in the next section,
when we introduce *weight decay*,
your first practical regularization technique.
Notably, it can be difficult to compare
complexity among members of substantially different model classes
(say, decision trees vs. neural networks).

At this point, we must stress another important point
that we will revisit when introducing deep neural networks.
When a model is capable of fitting arbitrary labels,
low training error does not necessarily
imply low generalization error.
*However, it does not necessarily
imply high generalization error either!*
All we can say with confidence is that
low training error alone is not enough
to certify low generalization error.
Deep neural networks turn out to be just such models:
while they generalize well in practice,
they are too powerful to allow us to conclude
much on the basis of training error alone.
In these cases we must rely more heavily
on our holdout data to certify generalization
after the fact.
Error on the holdout data, i.e., validation set,
is called the *validation error*.

### Underfitting or Overfitting?

When we compare the training and validation errors,
we want to be mindful of two common situations.
First, we want to watch out for cases
when our training error and validation error are both substantial
but there is a little gap between them.
If the model is unable to reduce the training error,
that could mean that our model is too simple
(i.e., insufficiently expressive)
to capture the pattern that we are trying to model.
Moreover, since the *generalization gap* ($R_\textrm{emp} - R$)
between our training and generalization errors is small,
we have reason to believe that we could get away with a more complex model.
This phenomenon is known as *underfitting*.

On the other hand, as we discussed above,
we want to watch out for the cases
when our training error is significantly lower
than our validation error, indicating severe *overfitting*.
Note that overfitting is not always a bad thing.
In deep learning especially,
the best predictive models often perform
far better on training data than on holdout data.
Ultimately, we usually care about
driving the generalization error lower,
and only care about the gap insofar
as it becomes an obstacle to that end.
Note that if the training error is zero,
then the generalization gap is precisely equal to the generalization error
and we can make progress only by reducing the gap.

#### Polynomial Curve Fitting

To illustrate some classical intuition
about overfitting and model complexity,
consider the following:
given training data consisting of a single feature $x$
and a corresponding real-valued label $y$,
we try to find the polynomial of degree $d$

## Weight Decay

Now that we have characterized the problem of overfitting,
we can introduce our first *regularization* technique.
Recall that we can always mitigate overfitting
by collecting more training data.
However, that can be costly, time consuming,
or entirely out of our control,
making it impossible in the short run.
For now, we can assume that we already have
as much high-quality data as our resources permit
and focus the tools at our disposal
when the dataset is taken as a given.

Recall that in our polynomial regression example
()
we could limit our model's capacity
by tweaking the degree
of the fitted polynomial.
Indeed, limiting the number of features
is a popular technique for mitigating overfitting.
However, simply tossing aside features
can be too blunt an instrument.
Sticking with the polynomial regression
example, consider what might happen
with high-dimensional input.
The natural extensions of polynomials
to multivariate data are called *monomials*,
which are simply products of powers of variables.
The degree of a monomial is the sum of the powers.
For example, $x_1^2 x_2$, and $x_3 x_5^2$
are both monomials of degree 3.

Note that the number of terms with degree $d$
blows up rapidly as $d$ grows larger.
Given $k$ variables, the number of monomials
of degree $d$ is ${k - 1 + d} \choose {k - 1}$.
Even small changes in degree, say from $2$ to $3$,
dramatically increase the complexity of our model.
Thus we often need a more fine-grained tool
for adjusting function complexity.

### Norms and Weight Decay

(**Rather than directly manipulating the number of parameters,
*weight decay*, operates by restricting the values
that the parameters can take.**)
More commonly called $\ell_2$ regularization
outside of deep learning circles
when optimized by minibatch stochastic gradient descent,
weight decay might be the most widely used technique
for regularizing parametric machine learning models.
The technique is motivated by the basic intuition
that among all functions $f$,
the function $f = 0$
(assigning the value $0$ to all inputs)
is in some sense the *simplest*,
and that we can measure the complexity
of a function by the distance of its parameters from zero.
But how precisely should we measure
the distance between a function and zero?
There is no single right answer.
In fact, entire branches of mathematics,
including parts of functional analysis
and the theory of Banach spaces,
are devoted to addressing such issues.

One simple interpretation might be
to measure the complexity of a linear function
$f(\mathbf{x}) = \mathbf{w}^\top \mathbf{x}$
by some norm of its weight vector, e.g., $\| \mathbf{w} \|^2$.
Recall that we introduced the $\ell_2$ norm and $\ell_1$ norm,
which are special cases of the more general $\ell_p$ norm,
in .
The most common method for ensuring a small weight vector
is to add its norm as a penalty term
to the problem of minimizing the loss.
Thus we replace our original objective,
*minimizing the prediction loss on the training labels*,
with new objective,
*minimizing the sum of the prediction loss and the penalty term*.
Now, if our weight vector grows too large,
our learning algorithm might focus
on minimizing the weight norm $\| \mathbf{w} \|^2$
rather than minimizing the training error.
That is exactly what we want.
To illustrate things in code,
we revive our previous example
from  for linear regression.
There, our loss was given by

For $\lambda = 0$, we recover our original loss function.
For $\lambda > 0$, we restrict the size of $\| \mathbf{w} \|$.
We divide by $2$ by convention:
when we take the derivative of a quadratic function,
the $2$ and $1/2$ cancel out, ensuring that the expression
for the update looks nice and simple.
The astute reader might wonder why we work with the squared
norm and not the standard norm (i.e., the Euclidean distance).
We do this for computational convenience.
By squaring the $\ell_2$ norm, we remove the square root,
leaving the sum of squares of
each component of the weight vector.
This makes the derivative of the penalty easy to compute:
the sum of derivatives equals the derivative of the sum.

Moreover, you might ask why we work with the $\ell_2$ norm
in the first place and not, say, the $\ell_1$ norm.
In fact, other choices are valid and
popular throughout statistics.
While $\ell_2$-regularized linear models constitute
the classic *ridge regression* algorithm,
$\ell_1$-regularized linear regression
is a similarly fundamental method in statistics,
popularly known as *lasso regression*.
One reason to work with the $\ell_2$ norm
is that it places an outsize penalty
on large components of the weight vector.
This biases our learning algorithm
towards models that distribute weight evenly
across a larger number of features.
In practice, this might make them more robust
to measurement error in a single variable.
By contrast, $\ell_1$ penalties lead to models
that concentrate weights on a small set of features
by clearing the other weights to zero.
This gives us an effective method for *feature selection*,
which may be desirable for other reasons.
For example, if our model only relies on a few features,
then we may not need to collect, store, or transmit data
for the other (dropped) features.

Using the same notation in ,
minibatch stochastic gradient descent updates
for $\ell_2$-regularized regression as follows:

# Multilayer Perceptrons

In this chapter, we will introduce your first truly *deep* network.
The simplest deep networks are called *multilayer perceptrons*,
and they consist of multiple layers of neurons
each fully connected to those in the layer below
(from which they receive input)
and those above (which they, in turn, influence).
Although automatic differentiation
significantly simplifies the implementation of deep learning algorithms,
we will dive deep into how these gradients
are calculated in deep networks.
Then we will
be ready to
discuss issues relating to numerical stability and parameter initialization
that are key to successfully training deep networks.
When we train such high-capacity models we run the risk of overfitting. Thus, we will
revisit regularization and generalization
for deep networks.
Throughout, we aim
to give you a firm grasp not just of the concepts but also of the practice of using deep networks.
At the end of this chapter, we apply what we have introduced so far to a real case: house price
prediction. We punt matters relating to the computational performance, scalability, and efficiency
of our models to subsequent chapters.

## Multilayer Perceptrons

In , we introduced
softmax regression,
implementing the algorithm from scratch
() and using high-level APIs
(). This allowed us to
train classifiers capable of recognizing
10 categories of clothing from low-resolution images.
Along the way, we learned how to wrangle data,
coerce our outputs into a valid probability distribution,
apply an appropriate loss function,
and minimize it with respect to our model's parameters.
Now that we have mastered these mechanics
in the context of simple linear models,
we can launch our exploration of deep neural networks,
the comparatively rich class of models
with which this book is primarily concerned.

### Hidden Layers

We described affine transformations in
linear transformations with added bias.
To begin, recall the model architecture
corresponding to our softmax regression example,
illustrated in  .
This model maps inputs directly to outputs
via a single affine transformation,
followed by a softmax operation.
If our labels truly were related
to the input data by a simple affine transformation,
then this approach would be sufficient.
However, linearity (in affine transformations) is a *strong* assumption.

#### Limitations of Linear Models

For example, linearity implies the *weaker*
assumption of *monotonicity*, i.e.,
that any increase in our feature must
either always cause an increase in our model's output
(if the corresponding weight is positive),
or always cause a decrease in our model's output
(if the corresponding weight is negative).
Sometimes that makes sense.
For example, if we were trying to predict
whether an individual will repay a loan,
we might reasonably assume that all other things being equal,
an applicant with a higher income
would always be more likely to repay
than one with a lower income.
While monotonic, this relationship likely
is not linearly associated with the probability of
repayment. An increase in income from \$0 to \$50,000
likely corresponds to a bigger increase
in likelihood of repayment
than an increase from \$1 million to \$1.05 million.
One way to handle this might be to postprocess our outcome
such that linearity becomes more plausible,
by using the logistic map (and thus the logarithm of the probability of outcome).

Note that we can easily come up with examples
that violate monotonicity.
Say for example that we want to predict health as a function
of body temperature.
For individuals with a normal body temperature
above 37°C (98.6°F),
higher temperatures indicate greater risk.
However, if the body temperatures drops
below 37°C, lower temperatures indicate greater risk!
Again, we might resolve the problem
with some clever preprocessing, such as using the distance from 37°C
as a feature.

But what about classifying images of cats and dogs?
Should increasing the intensity
of the pixel at location (13, 17)
always increase (or always decrease)
the likelihood that the image depicts a dog?
Reliance on a linear model corresponds to the implicit
assumption that the only requirement
for differentiating cats and dogs is to assess
the brightness of individual pixels.
This approach is doomed to fail in a world
where inverting an image preserves the category.

And yet despite the apparent absurdity of linearity here,
as compared with our previous examples,
it is less obvious that we could address the problem
with a simple preprocessing fix.
That is, because the significance of any pixel
depends in complex ways on its context
(the values of the surrounding pixels).
While there might exist a representation of our data
that would take into account
the relevant interactions among our features,
on top of which a linear model would be suitable,
we simply do not know how to calculate it by hand.
With deep neural networks, we used observational data
to jointly learn both a representation via hidden layers
and a linear predictor that acts upon that representation.

This problem of nonlinearity has been studied for at least a
century . For instance, decision trees
in their most basic form use a sequence of binary decisions to
decide upon class membership . Likewise, kernel
methods have been used for many decades to model nonlinear dependencies
nonparametric spline models  and kernel methods
quite naturally. After all, neurons feed into other neurons which,
in turn, feed into other neurons again .
Consequently we have a sequence of relatively simple transformations.

#### Incorporating Hidden Layers

We can overcome the limitations of linear models
by incorporating one or more hidden layers.
The easiest way to do this is to stack
many fully connected layers on top of one another.
Each layer feeds into the layer above it,
until we generate outputs.
We can think of the first $L-1$ layers
as our representation and the final layer
as our linear predictor.
This architecture is commonly called
a *multilayer perceptron*,
often abbreviated as *MLP* ().

This MLP has four inputs, three outputs,
and its hidden layer contains five hidden units.
Since the input layer does not involve any calculations,
producing outputs with this network
requires implementing the computations
for both the hidden and output layers;
thus, the number of layers in this MLP is two.
Note that both layers are fully connected.
Every input influences every neuron in the hidden layer,
and each of these in turn influences
every neuron in the output layer. Alas, we are not quite
done yet.

#### From Linear to Nonlinear

As before, we denote by the matrix $\mathbf{X} \in \mathbb{R}^{n \times d}$
a minibatch of $n$ examples where each example has $d$ inputs (features).
For a one-hidden-layer MLP whose hidden layer has $h$ hidden units,
we denote by $\mathbf{H} \in \mathbb{R}^{n \times h}$
the outputs of the hidden layer, which are
*hidden representations*.
Since the hidden and output layers are both fully connected,
we have hidden-layer weights $\mathbf{W}^{(1)} \in \mathbb{R}^{d \times h}$ and biases $\mathbf{b}^{(1)} \in \mathbb{R}^{1 \times h}$
and output-layer weights $\mathbf{W}^{(2)} \in \mathbb{R}^{h \times q}$ and biases $\mathbf{b}^{(2)} \in \mathbb{R}^{1 \times q}$.
This allows us to calculate the outputs $\mathbf{O} \in \mathbb{R}^{n \times q}$
of the one-hidden-layer MLP as follows:

Note that after adding the hidden layer,
our model now requires us to track and update
additional sets of parameters.
So what have we gained in exchange?
You might be surprised to find out
that---in the model defined above---*we
gain nothing for our troubles*!
The reason is plain.
The hidden units above are given by
an affine function of the inputs,
and the outputs (pre-softmax) are just
an affine function of the hidden units.
An affine function of an affine function
is itself an affine function.
Moreover, our linear model was already
capable of representing any affine function.

To see this formally we can just collapse out the hidden layer in the above definition,
yielding an equivalent single-layer model with parameters
$\mathbf{W} = \mathbf{W}^{(1)}\mathbf{W}^{(2)}$ and $\mathbf{b} = \mathbf{b}^{(1)} \mathbf{W}^{(2)} + \mathbf{b}^{(2)}$:

In order to realize the potential of multilayer architectures,
we need one more key ingredient: a
nonlinear *activation function* $\sigma$
to be applied to each hidden unit
following the affine transformation. For instance, a popular
choice is the ReLU (rectified linear unit) activation function
$\sigma(x) = \mathrm{max}(0, x)$ operating on its arguments elementwise.
The outputs of activation functions $\sigma(\cdot)$
are called *activations*.
In general, with activation functions in place,
it is no longer possible to collapse our MLP into a linear model:

Since each row in $\mathbf{X}$ corresponds to an example in the minibatch,
with some abuse of notation, we define the nonlinearity
$\sigma$ to apply to its inputs in a rowwise fashion,
i.e., one example at a time.
Note that we used the same notation for softmax
when we denoted a rowwise operation in .
Quite frequently the activation functions we use apply not merely rowwise but
elementwise. That means that after computing the linear portion of the layer,
we can calculate each activation
without looking at the values taken by the other hidden units.

To build more general MLPs, we can continue stacking
such hidden layers,
e.g., $\mathbf{H}^{(1)} = \sigma_1(\mathbf{X} \mathbf{W}^{(1)} + \mathbf{b}^{(1)})$
and $\mathbf{H}^{(2)} = \sigma_2(\mathbf{H}^{(1)} \mathbf{W}^{(2)} + \mathbf{b}^{(2)})$,
one atop another, yielding ever more expressive models.

#### Universal Approximators

We know that the brain is capable of very sophisticated statistical analysis. As such,
it is worth asking, just *how powerful* a deep network could be. This question
has been answered multiple times, e.g., in  in the context
of MLPs, and in  in the context of reproducing kernel
Hilbert spaces in a way that could be seen as radial basis function (RBF) networks with a single hidden layer.
These (and related results) suggest that even with a single-hidden-layer network,
given enough nodes (possibly absurdly many),
and the right set of weights,
we can model any function.
Actually learning that function is the hard part, though.
You might think of your neural network
as being a bit like the C programming language.
The language, like any other modern language,
is capable of expressing any computable program.
But actually coming up with a program
that meets your specifications is the hard part.

Moreover, just because a single-hidden-layer network
*can* learn any function
does not mean that you should try
to solve all of your problems
with one. In fact, in this case kernel methods
are way more effective, since they are capable of solving the problem
*exactly* even in infinite dimensional spaces .
In fact, we can approximate many functions
much more compactly by using deeper (rather than wider) networks .
We will touch upon more rigorous arguments in subsequent chapters.

### Activation Functions

Activation functions decide whether a neuron should be activated or not by
calculating the weighted sum and further adding bias to it.
They are differentiable operators for transforming input signals to outputs,
while most of them add nonlinearity.
Because activation functions are fundamental to deep learning,
(**let's briefly survey some common ones**).

#### ReLU Function

The most popular choice,
due to both simplicity of implementation and
its good performance on a variety of predictive tasks,
is the *rectified linear unit* (*ReLU*) .
[**ReLU provides a very simple nonlinear transformation**].
Given an element $x$, the function is defined
as the maximum of that element and $0$:

#### Sigmoid Function

[**The *sigmoid function* transforms those inputs**]
whose values lie in the domain $\mathbb{R}$,
(**to outputs that lie on the interval (0, 1).**)
For that reason, the sigmoid is
often called a *squashing function*:
it squashes any input in the range (-inf, inf)
to some value in the range (0, 1):

The derivative of the sigmoid function is plotted below.
Note that when the input is 0,
the derivative of the sigmoid function
reaches a maximum of 0.25.
As the input diverges from 0 in either direction,
the derivative approaches 0.

#### Tanh Function

Like the sigmoid function, [**the tanh (hyperbolic tangent)
function also squashes its inputs**],
transforming them into elements on the interval (**between $-1$ and $1$**):

It is plotted below.
As the input nears 0,
the derivative of the tanh function approaches a maximum of 1.
And as we saw with the sigmoid function,
as input moves away from 0 in either direction,
the derivative of the tanh function approaches 0.

### Summary and Discussion

We now know how to incorporate nonlinearities
to build expressive multilayer neural network architectures.
As a side note, your knowledge already
puts you in command of a similar toolkit
to a practitioner circa 1990.
In some ways, you have an advantage
over anyone working back then,
because you can leverage powerful
open-source deep learning frameworks
to build models rapidly, using only a few lines of code.
Previously, training these networks
required researchers to code up layers and derivatives
explicitly in C, Fortran, or even Lisp (in the case of LeNet).

A secondary benefit is that ReLU is significantly more amenable to
optimization than the sigmoid or the tanh function. One could argue
that this was one of the key innovations that helped the resurgence
of deep learning over the past decade. Note, though, that research in
activation functions has not stopped.
For instance,
the GELU (Gaussian error linear unit)
activation function $x \Phi(x)$ by  ($\Phi(x)$
is the standard Gaussian cumulative distribution function)
and
the Swish activation
function $\sigma(x) = x \operatorname{sigmoid}(\beta x)$ as proposed in  can yield better accuracy
in many cases.

### Exercises

1. Show that adding layers to a *linear* deep network, i.e., a network without
   nonlinearity $\sigma$ can never increase the expressive power of the network.
   Give an example where it actively reduces it.
1. Compute the derivative of the pReLU activation function.
1. Compute the derivative of the Swish activation function $x \operatorname{sigmoid}(\beta x)$.
1. Show that an MLP using only ReLU (or pReLU) constructs a
   continuous piecewise linear function.
1. Sigmoid and tanh are very similar.
    1. Show that $\operatorname{tanh}(x) + 1 = 2 \operatorname{sigmoid}(2x)$.
    1. Prove that the function classes parametrized by both nonlinearities are identical. Hint: affine layers have bias terms, too.
1. Assume that we have a nonlinearity that applies to one minibatch at a time, such as the batch normalization . What kinds of problems do you expect this to cause?
1. Provide an example where the gradients vanish for the sigmoid activation function.

[Discussions](https://discuss.d2l.ai/t/90)

[Discussions](https://discuss.d2l.ai/t/91)

[Discussions](https://discuss.d2l.ai/t/226)

[Discussions](https://discuss.d2l.ai/t/17984)

## Forward Propagation, Backward Propagation, and Computational Graphs

So far, we have trained our models
with minibatch stochastic gradient descent.
However, when we implemented the algorithm,
we only worried about the calculations involved
in *forward propagation* through the model.
When it came time to calculate the gradients,
we just invoked the backpropagation function provided by the deep learning framework.

The automatic calculation of gradients
profoundly simplifies
the implementation of deep learning algorithms.
Before automatic differentiation,
even small changes to complicated models required
recalculating complicated derivatives by hand.
Surprisingly often, academic papers had to allocate
numerous pages to deriving update rules.
While we must continue to rely on automatic differentiation
so we can focus on the interesting parts,
you ought to know how these gradients
are calculated under the hood
if you want to go beyond a shallow
understanding of deep learning.

In this section, we take a deep dive
into the details of *backward propagation*
(more commonly called *backpropagation*).
To convey some insight for both the
techniques and their implementations,
we rely on some basic mathematics and computational graphs.
To start, we focus our exposition on
a one-hidden-layer MLP
with weight decay ($\ell_2$ regularization, to be described in subsequent chapters).

### Forward Propagation

*Forward propagation* (or *forward pass*) refers to the calculation and storage
of intermediate variables (including outputs)
for a neural network in order
from the input layer to the output layer.
We now work step-by-step through the mechanics
of a neural network with one hidden layer.
This may seem tedious but in the eternal words
of funk virtuoso James Brown,
you must "pay the cost to be the boss".

For the sake of simplicity, let's assume
that the input example is $\mathbf{x}\in \mathbb{R}^d$
and that our hidden layer does not include a bias term.
Here the intermediate variable is:

The hidden layer output $\mathbf{h}$
is also an intermediate variable.
Assuming that the parameters of the output layer
possess only a weight of
$\mathbf{W}^{(2)} \in \mathbb{R}^{q \times h}$,
we can obtain an output layer variable
with a vector of length $q$:

As we will see the definition of $\ell_2$ regularization
to be introduced later,
given the hyperparameter $\lambda$,
the regularization term is

We refer to $J$ as the *objective function*
in the following discussion.

### Computational Graph of Forward Propagation

Plotting *computational graphs* helps us visualize
the dependencies of operators
and variables within the calculation.
with the simple network described above,
where squares denote variables and circles denote operators.
The lower-left corner signifies the input
and the upper-right corner is the output.
Notice that the directions of the arrows
(which illustrate data flow)
are primarily rightward and upward.

### Backpropagation

*Backpropagation* refers to the method of calculating
the gradient of neural network parameters.
In short, the method traverses the network in reverse order,
from the output to the input layer,
according to the *chain rule* from calculus.
The algorithm stores any intermediate variables
(partial derivatives)
required while calculating the gradient
with respect to some parameters.
Assume that we have functions
$\mathsf{Y}=f(\mathsf{X})$
and $\mathsf{Z}=g(\mathsf{Y})$,
in which the input and the output
$\mathsf{X}, \mathsf{Y}, \mathsf{Z}$
are tensors of arbitrary shapes.
By using the chain rule,
we can compute the derivative
of $\mathsf{Z}$ with respect to $\mathsf{X}$ via

Next, we compute the gradient of the objective function
with respect to variable of the output layer $\mathbf{o}$
according to the chain rule:

Next, we calculate the gradients
of the regularization term
with respect to both parameters:

To obtain the gradient with respect to $\mathbf{W}^{(1)}$
we need to continue backpropagation
along the output layer to the hidden layer.
The gradient with respect to the hidden layer output
$\partial J/\partial \mathbf{h} \in \mathbb{R}^h$ is given by

Since the activation function $\phi$ applies elementwise,
calculating the gradient $\partial J/\partial \mathbf{z} \in \mathbb{R}^h$
of the intermediate variable $\mathbf{z}$
requires that we use the elementwise multiplication operator,
which we denote by $\odot$:

Finally, we can obtain the gradient
$\partial J/\partial \mathbf{W}^{(1)} \in \mathbb{R}^{h \times d}$
of the model parameters closest to the input layer.
According to the chain rule, we get

### Training Neural Networks

When training neural networks,
forward and backward propagation depend on each other.
In particular, for forward propagation,
we traverse the computational graph in the direction of dependencies
and compute all the variables on its path.
These are then used for backpropagation
where the compute order on the graph is reversed.

Take the aforementioned simple network as an illustrative example.
On the one hand,
computing the regularization term
during forward propagation
depends on the current values of model parameters $\mathbf{W}^{(1)}$ and $\mathbf{W}^{(2)}$.
They are given by the optimization algorithm according to backpropagation in the most recent iteration.
On the other hand,
the gradient calculation for the parameter
depends on the current value of the hidden layer output $\mathbf{h}$,
which is given by forward propagation.

Therefore when training neural networks, once model parameters are initialized,
we alternate forward propagation with backpropagation,
updating model parameters using gradients given by backpropagation.
Note that backpropagation reuses the stored intermediate values from forward propagation to avoid duplicate calculations.
One of the consequences is that we need to retain
the intermediate values until backpropagation is complete.
This is also one of the reasons why training
requires significantly more memory than plain prediction.
Besides, the size of such intermediate values is roughly
proportional to the number of network layers and the batch size.
Thus,
training deeper networks using larger batch sizes
more easily leads to *out-of-memory* errors.

### Summary

Forward propagation sequentially calculates and stores intermediate variables within the computational graph defined by the neural network. It proceeds from the input to the output layer.
Backpropagation sequentially calculates and stores the gradients of intermediate variables and parameters within the neural network in the reversed order.
When training deep learning models, forward propagation and backpropagation are interdependent,
and training requires significantly more memory than prediction.

### Exercises

1. Assume that the inputs $\mathbf{X}$ to some scalar function $f$ are $n \times m$ matrices. What is the dimensionality of the gradient of $f$ with respect to $\mathbf{X}$?
1. Add a bias to the hidden layer of the model described in this section (you do not need to include bias in the regularization term).
    1. Draw the corresponding computational graph.
    1. Derive the forward and backward propagation equations.
1. Compute the memory footprint for training and prediction in the model described in this section.
1. Assume that you want to compute second derivatives. What happens to the computational graph? How long do you expect the calculation to take?
1. Assume that the computational graph is too large for your GPU.
    1. Can you partition it over more than one GPU?
    1. What are the advantages and disadvantages over training on a smaller minibatch?

[Discussions](https://discuss.d2l.ai/t/102)

## Numerical Stability and Initialization

Thus far, every model that we have implemented
required that we initialize its parameters
according to some pre-specified distribution.
Until now, we took the initialization scheme for granted,
glossing over the details of how these choices are made.
You might have even gotten the impression that these choices
are not especially important.
On the contrary, the choice of initialization scheme
plays a significant role in neural network learning,
and it can be crucial for maintaining numerical stability.
Moreover, these choices can be tied up in interesting ways
with the choice of the nonlinear activation function.
Which function we choose and how we initialize parameters
can determine how quickly our optimization algorithm converges.
Poor choices here can cause us to encounter
exploding or vanishing gradients while training.
In this section, we delve into these topics in greater detail
and discuss some useful heuristics
that you will find useful
throughout your career in deep learning.

### Vanishing and Exploding Gradients

Consider a deep network with $L$ layers,
input $\mathbf{x}$ and output $\mathbf{o}$.
With each layer $l$ defined by a transformation $f_l$
parametrized by weights $\mathbf{W}^{(l)}$,
whose hidden layer output is $\mathbf{h}^{(l)}$ (let $\mathbf{h}^{(0)} = \mathbf{x}$),
our network can be expressed as:

In other words, this gradient is
the product of $L-l$ matrices
$\mathbf{M}^{(L)} \cdots \mathbf{M}^{(l+1)}$
and the gradient vector $\mathbf{v}^{(l)}$.
Thus we are susceptible to the same
problems of numerical underflow that often crop up
when multiplying together too many probabilities.
When dealing with probabilities, a common trick is to
switch into log-space, i.e., shifting
pressure from the mantissa to the exponent
of the numerical representation.
Unfortunately, our problem above is more serious:
initially the matrices $\mathbf{M}^{(l)}$ may have a wide variety of eigenvalues.
They might be small or large, and
their product might be *very large* or *very small*.

The risks posed by unstable gradients
go beyond numerical representation.
Gradients of unpredictable magnitude
also threaten the stability of our optimization algorithms.
We may be facing parameter updates that are either
(i) excessively large, destroying our model
(the *exploding gradient* problem);
or (ii) excessively small
(the *vanishing gradient* problem),
rendering learning impossible as parameters
hardly move on each update.

#### (**Vanishing Gradients**)

One frequent culprit causing the vanishing gradient problem
is the choice of the activation function $\sigma$
that is appended following each layer's linear operations.
Historically, the sigmoid function
$1/(1 + \exp(-x))$ (introduced in )
was popular because it resembles a thresholding function.
Since early artificial neural networks were inspired
by biological neural networks,
the idea of neurons that fire either *fully* or *not at all*
(like biological neurons) seemed appealing.
Let's take a closer look at the sigmoid
to see why it can cause vanishing gradients.

As you can see, (**the sigmoid's gradient vanishes
both when its inputs are large and when they are small**).
Moreover, when backpropagating through many layers,
unless we are in the Goldilocks zone, where
the inputs to many of the sigmoids are close to zero,
the gradients of the overall product may vanish.
When our network boasts many layers,
unless we are careful, the gradient
will likely be cut off at some layer.
Indeed, this problem used to plague deep network training.
Consequently, ReLUs, which are more stable
(but less neurally plausible),
have emerged as the default choice for practitioners.

#### [**Exploding Gradients**]

The opposite problem, when gradients explode,
can be similarly vexing.
To illustrate this a bit better,
we draw 100 Gaussian random matrices
and multiply them with some initial matrix.
For the scale that we picked
(the choice of the variance $\sigma^2=1$),
the matrix product explodes.
When this happens because of the initialization
of a deep network, we have no chance of getting
a gradient descent optimizer to converge.

#### Breaking the Symmetry

Another problem in neural network design
is the symmetry inherent in their parametrization.
Assume that we have a simple MLP
with one hidden layer and two units.
In this case, we could permute the weights $\mathbf{W}^{(1)}$
of the first layer and likewise permute
the weights of the output layer
to obtain the same function.
There is nothing special differentiating
the first and second hidden units.
In other words, we have permutation symmetry
among the hidden units of each layer.

This is more than just a theoretical nuisance.
Consider the aforementioned one-hidden-layer MLP
with two hidden units.
For illustration,
suppose that the output layer transforms the two hidden units into only one output unit.
Imagine what would happen if we initialized
all the parameters of the hidden layer
as $\mathbf{W}^{(1)} = c$ for some constant $c$.
In this case, during forward propagation
either hidden unit takes the same inputs and parameters
producing the same activation
which is fed to the output unit.
During backpropagation,
differentiating the output unit with respect to parameters $\mathbf{W}^{(1)}$ gives a gradient all of whose elements take the same value.
Thus, after gradient-based iteration (e.g., minibatch stochastic gradient descent),
all the elements of $\mathbf{W}^{(1)}$ still take the same value.
Such iterations would
never *break the symmetry* on their own
and we might never be able to realize
the network's expressive power.
The hidden layer would behave
as if it had only a single unit.
Note that while minibatch stochastic gradient descent would not break this symmetry,
dropout regularization (to be introduced later) would!

### Parameter Initialization

One way of addressing---or at least mitigating---the
issues raised above is through careful initialization.
As we will see later,
additional care during optimization
and suitable regularization can further enhance stability.

#### Default Initialization

In the previous sections, e.g., in ,
we used a normal distribution
to initialize the values of our weights.
If we do not specify the initialization method, the framework will
use a default random initialization method, which often works well in practice
for moderate problem sizes.

#### Xavier Initialization

Let's look at the scale distribution of
an output $o_{i}$ for some fully connected layer
*without nonlinearities*.
With $n_\textrm{in}$ inputs $x_j$
and their associated weights $w_{ij}$ for this layer,
an output is given by

\begin{aligned}
    E[o_i] & = \sum_{j=1}^{n_\textrm{in}} E[w_{ij} x_j] \\&= \sum_{j=1}^{n_\textrm{in}} E[w_{ij}] E[x_j] \\&= 0, \end{aligned}$$

and the variance:

One way to keep the variance fixed
is to set $n_\textrm{in} \sigma^2 = 1$.
Now consider backpropagation.
There we face a similar problem,
albeit with gradients being propagated from the layers closer to the output.
Using the same reasoning as for forward propagation,
we see that the gradients' variance can blow up
unless $n_\textrm{out} \sigma^2 = 1$,
where $n_\textrm{out}$ is the number of outputs of this layer.
This leaves us in a dilemma:
we cannot possibly satisfy both conditions simultaneously.
Instead, we simply try to satisfy:

This is the reasoning underlying the now-standard
and practically beneficial *Xavier initialization*,
named after the first author of its creators .
Typically, the Xavier initialization
samples weights from a Gaussian distribution
with zero mean and variance
$\sigma^2 = \frac{2}{n_\textrm{in} + n_\textrm{out}}$.
We can also adapt this to
choose the variance when sampling weights
from a uniform distribution.
Note that the uniform distribution $U(-a, a)$ has variance $\frac{a^2}{3}$.
Plugging $\frac{a^2}{3}$ into our condition on $\sigma^2$
prompts us to initialize according to

## Generalization in Deep Learning

In  and ,
we tackled regression and classification problems
by fitting linear models to training data.
In both cases, we provided practical algorithms
for finding the parameters that maximized
the likelihood of the observed training labels.
And then, towards the end of each chapter,
we recalled that fitting the training data
was only an intermediate goal.
Our real quest all along was to discover *general patterns*
on the basis of which we can make accurate predictions
even on new examples drawn from the same underlying population.
Machine learning researchers are *consumers* of optimization algorithms.
Sometimes, we must even develop new optimization algorithms.
But at the end of the day, optimization is merely a means to an end.
At its core, machine learning is a statistical discipline
and we wish to optimize training loss only insofar
as some statistical principle (known or unknown)
leads the resulting models to generalize beyond the training set.

On the bright side, it turns out that deep neural networks
trained by stochastic gradient descent generalize remarkably well
across myriad prediction problems, spanning computer vision;
natural language processing; time series data; recommender systems;
electronic health records; protein folding;
value function approximation in video games
and board games; and numerous other domains.
On the downside, if you were looking
for a straightforward account
of either the optimization story
(why we can fit them to training data)
or the generalization story
(why the resulting models generalize to unseen examples),
then you might want to pour yourself a drink.
While our procedures for optimizing linear models
and the statistical properties of the solutions
are both described well by a comprehensive body of theory,
our understanding of deep learning
still resembles the wild west on both fronts.

Both the theory and practice of deep learning
are rapidly evolving,
with theorists adopting new strategies
to explain what's going on,
even as practitioners continue
to innovate at a blistering pace,
building arsenals of heuristics for training deep networks
and a body of intuitions and folk knowledge
that provide guidance for deciding
which techniques to apply in which situations.

The summary of the present moment is that the theory of deep learning
has produced promising lines of attack and scattered fascinating results,
but still appears far from a comprehensive account
of both (i) why we are able to optimize neural networks
and (ii) how models learned by gradient descent
manage to generalize so well, even on high-dimensional tasks.
However, in practice, (i) is seldom a problem
(we can always find parameters that will fit all of our training data)
and thus understanding generalization is far the bigger problem.
On the other hand, even absent the comfort of a coherent scientific theory,
practitioners have developed a large collection of techniques
that may help you to produce models that generalize well in practice.
While no pithy summary can possibly do justice
to the vast topic of generalization in deep learning,
and while the overall state of research is far from resolved,
we hope, in this section, to present a broad overview
of the state of research and practice.

### Revisiting Overfitting and Regularization

According to the "no free lunch" theorem of ,
any learning algorithm generalizes better on data with certain distributions, and worse with other distributions.
Thus, given a finite training set,
a model relies on certain assumptions:
to achieve human-level performance
it may be useful to identify *inductive biases*
that reflect how humans think about the world.
Such inductive biases show preferences
for solutions with certain properties.
For example,
a deep MLP has an inductive bias
towards building up a complicated function by the composition of simpler functions.

With machine learning models encoding inductive biases,
our approach to training them
typically consists of two phases: (i) fit the training data;
and (ii) estimate the *generalization error*
(the true error on the underlying population)
by evaluating the model on holdout data.
The difference between our fit on the training data
and our fit on the test data is called the *generalization gap* and when this is large,
we say that our models *overfit* to the training data.
In extreme cases of overfitting,
we might exactly fit the training data,
even when the test error remains significant.
And in the classical view,
the interpretation is that our models are too complex,
requiring that we either shrink the number of features,
the number of nonzero parameters learned,
or the size of the parameters as quantified.
Recall the plot of model complexity compared with loss
()
from .

However deep learning complicates this picture in counterintuitive ways.
First, for classification problems,
our models are typically expressive enough
to perfectly fit every training example,
even in datasets consisting of millions
In the classical picture, we might think
that this setting lies on the far right extreme
of the model complexity axis,
and that any improvements in generalization error
must come by way of regularization,
either by reducing the complexity of the model class,
or by applying a penalty, severely constraining
the set of values that our parameters might take.
But that is where things start to get weird.

Strangely, for many deep learning tasks
(e.g., image recognition and text classification)
we are typically choosing among model architectures,
all of which can achieve arbitrarily low training loss
(and zero training error).
Because all models under consideration achieve zero training error,
*the only avenue for further gains is to reduce overfitting*.
Even stranger, it is often the case that
despite fitting the training data perfectly,
we can actually *reduce the generalization error*
further by making the model *even more expressive*,
e.g., adding layers, nodes, or training
for a larger number of epochs.
Stranger yet, the pattern relating the generalization gap
to the *complexity* of the model (as captured, for example, in the depth or width of the networks)
can be non-monotonic,
with greater complexity hurting at first
but subsequently helping in a so-called "double-descent" pattern
Thus the deep learning practitioner possesses a bag of tricks,
some of which seemingly restrict the model in some fashion
and others that seemingly make it even more expressive,
and all of which, in some sense, are applied to mitigate overfitting.

Complicating things even further,
while the guarantees provided by classical learning theory
can be conservative even for classical models,
they appear powerless to explain why it is
that deep neural networks generalize in the first place.
Because deep neural networks are capable of fitting
arbitrary labels even for large datasets,
and despite the use of familiar methods such as $\ell_2$ regularization,
traditional complexity-based generalization bounds,
e.g., those based on the VC dimension
or Rademacher complexity of a hypothesis class
cannot explain why neural networks generalize.

### Inspiration from Nonparametrics

Approaching deep learning for the first time,
it is tempting to think of them as parametric models.
After all, the models *do* have millions of parameters.
When we update the models, we update their parameters.
When we save the models, we write their parameters to disk.
However, mathematics and computer science are riddled
with counterintuitive changes of perspective,
and surprising isomorphisms between seemingly different problems.
While neural networks clearly *have* parameters,
in some ways it can be more fruitful
to think of them as behaving like nonparametric models.
So what precisely makes a model nonparametric?
While the name covers a diverse set of approaches,
one common theme is that nonparametric methods
tend to have a level of complexity that grows
as the amount of available data grows.

Perhaps the simplest example of a nonparametric model
is the $k$-nearest neighbor algorithm (we will cover more nonparametric models later, for example in ).
Here, at training time,
the learner simply memorizes the dataset.
Then, at prediction time,
when confronted with a new point $\mathbf{x}$,
the learner looks up the $k$ nearest neighbors
(the $k$ points $\mathbf{x}_i'$ that minimize
some distance $d(\mathbf{x}, \mathbf{x}_i')$).
When $k=1$, this algorithm is called $1$-nearest neighbors,
and the algorithm will always achieve a training error of zero.
That however, does not mean that the algorithm will not generalize.
In fact, it turns out that under some mild conditions,
the 1-nearest neighbor algorithm is consistent
(eventually converging to the optimal predictor).

Note that $1$-nearest neighbor requires that we specify
some distance function $d$, or equivalently,
that we specify some vector-valued basis function $\phi(\mathbf{x})$
for featurizing our data.
For any choice of the distance metric,
we will achieve zero training error
and eventually reach an optimal predictor,
but different distance metrics $d$
encode different inductive biases
and with a finite amount of available data
will yield different predictors.
Different choices of the distance metric $d$
represent different assumptions about the underlying patterns
and the performance of the different predictors
will depend on how compatible the assumptions
are with the observed data.

In a sense, because neural networks are over-parametrized,
possessing many more parameters than are needed to fit the training data,
they tend to *interpolate* the training data (fitting it perfectly)
and thus behave, in some ways, more like nonparametric models.
More recent theoretical research has established
deep connection between large neural networks
and nonparametric methods, notably kernel methods.
In particular,
demonstrated that in the limit, as multilayer perceptrons
with randomly initialized weights grow infinitely wide,
they become equivalent to (nonparametric) kernel methods
for a specific choice of the kernel function
(essentially, a distance function),
which they call the neural tangent kernel.
While current neural tangent kernel models may not fully explain
the behavior of modern deep networks,
their success as an analytical tool
underscores the usefulness of nonparametric modeling
for understanding the behavior of over-parametrized deep networks.

### Early Stopping

While deep neural networks are capable of fitting arbitrary labels,
even when labels are assigned incorrectly or randomly
this capability only emerges over many iterations of training.
A new line of work
has revealed that in the setting of label noise,
neural networks tend to fit cleanly labeled data first
and only subsequently to interpolate the mislabeled data.
Moreover, it has been established that this phenomenon
translates directly into a guarantee on generalization:
whenever a model has fitted the cleanly labeled data
but not randomly labeled examples included in the training set,
it has in fact generalized .

Together these findings help to motivate *early stopping*,
a classic technique for regularizing deep neural networks.
Here, rather than directly constraining the values of the weights,
one constrains the number of epochs of training.
The most common way to determine the stopping criterion
is to monitor validation error throughout training
(typically by checking once after each epoch)
and to cut off training when the validation error
has not decreased by more than some small amount $\epsilon$
for some number of epochs.
This is sometimes called a *patience criterion*.
As well as the potential to lead to better generalization
in the setting of noisy labels,
another benefit of early stopping is the time saved.
Once the patience criterion is met, one can terminate training.
For large models that might require days of training
simultaneously across eight or more GPUs,
well-tuned early stopping can save researchers days of time
and can save their employers many thousands of dollars.

Notably, when there is no label noise and datasets are *realizable*
(the classes are truly separable, e.g., distinguishing cats from dogs),
early stopping tends not to lead to significant improvements in generalization.
On the other hand, when there is label noise,
or intrinsic variability in the label
(e.g., predicting mortality among patients),
early stopping is crucial.
Training models until they interpolate noisy data is typically a bad idea.

### Classical Regularization Methods for Deep Networks

In , we described
several  classical regularization techniques
for constraining the complexity of our models.
In particular,
introduced a method called weight decay,
which consists of adding a regularization term to the loss function
in order to penalize large values of the weights.
Depending on which weight norm is penalized
this technique is known either as ridge regularization (for $\ell_2$ penalty)
or lasso regularization (for an $\ell_1$ penalty).
In the classical analysis of these regularizers,
they are considered as sufficiently restrictive on the values
that the weights can take to prevent the model from fitting arbitrary labels.

In deep learning implementations,
weight decay remains a popular tool.
However, researchers have noted
that typical strengths of $\ell_2$ regularization
are insufficient to prevent the networks
from interpolating the data  and thus the benefits if interpreted
as regularization might only make sense
in combination with the early stopping criterion.
Absent early stopping, it is possible
that just like the number of layers
or number of nodes (in deep learning)
or the distance metric (in 1-nearest neighbor),
these methods may lead to better generalization
not because they meaningfully constrain
the power of the neural network
but rather because they somehow encode inductive biases
that are better compatible with the patterns
found in datasets of interests.
Thus, classical regularizers remain popular
in deep learning implementations,
even if the theoretical rationale
for their efficacy may be radically different.

Notably, deep learning researchers have also built
on techniques first popularized
in classical regularization contexts,
such as adding noise to model inputs.
In the next section we will introduce
the famous dropout technique
(invented by ),
which has become a mainstay of deep learning,
even as the theoretical basis for its efficacy
remains similarly mysterious.

### Summary

Unlike classical linear models,
which tend to have fewer parameters than examples,
deep networks tend to be over-parametrized,
and for most tasks are capable
of perfectly fitting the training set.
This *interpolation regime* challenges
many hard fast-held intuitions.
Functionally, neural networks look like parametric models.
But thinking of them as nonparametric models
can sometimes be a more reliable source of intuition.
Because it is often the case that all deep networks under consideration
are capable of fitting all of the training labels,
nearly all gains must come by mitigating overfitting
(closing the *generalization gap*).
Paradoxically, the interventions
that reduce the generalization gap
sometimes appear to increase model complexity
and at other times appear to decrease complexity.
However, these methods seldom decrease complexity
sufficiently for classical theory
to explain the generalization of deep networks,
and *why certain choices lead to improved generalization*
remains for the most part a massive open question
despite the concerted efforts of many brilliant researchers.

### Exercises

1. In what sense do traditional complexity-based measures fail to account for generalization of deep neural networks?
1. Why might *early stopping* be considered a regularization technique?
1. How do researchers typically determine the stopping criterion?
1. What important factor seems to differentiate cases when early stopping leads to big improvements in generalization?
1. Beyond generalization, describe another benefit of early stopping.

[Discussions](https://discuss.d2l.ai/t/7473)

## Dropout

Let's think briefly about what we
expect from a good predictive model.
We want it to peform well on unseen data.
Classical generalization theory
suggests that to close the gap between
train and test performance,
we should aim for a simple model.
Simplicity can come in the form
of a small number of dimensions.
We explored this when discussing the
monomial basis functions of linear models
in .
Additionally, as we saw when discussing weight decay
($\ell_2$ regularization) in ,
the (inverse) norm of the parameters also
represents a useful measure of simplicity.
Another useful notion of simplicity is smoothness,
i.e., that the function should not be sensitive
to small changes to its inputs.
For instance, when we classify images,
we would expect that adding some random noise
to the pixels should be mostly harmless.

this idea when he proved that training with input noise
is equivalent to Tikhonov regularization.
This work drew a clear mathematical connection
between the requirement that a function be smooth (and thus simple),
and the requirement that it be resilient
to perturbations in the input.

Then,
developed a clever idea for how to apply Bishop's idea
to the internal layers of a network, too.
Their idea, called *dropout*, involves
injecting noise while computing
each internal layer during forward propagation,
and it has become a standard technique
for training neural networks.
The method is called *dropout* because we literally
*drop out* some neurons during training.
Throughout training, on each iteration,
standard dropout consists of zeroing out
some fraction of the nodes in each layer
before calculating the subsequent layer.

To be clear, we are imposing
our own narrative with the link to Bishop.
The original paper on dropout
offers intuition through a surprising
analogy to sexual reproduction.
The authors argue that neural network overfitting
is characterized by a state in which
each layer relies on a specific
pattern of activations in the previous layer,
calling this condition *co-adaptation*.
Dropout, they claim, breaks up co-adaptation
just as sexual reproduction is argued to
break up co-adapted genes.
While such an justification of this theory is certainly up for debate,
the dropout technique itself has proved enduring,
and various forms of dropout are implemented
in most deep learning libraries.

The key challenge is how to inject this noise.
One idea is to inject it in an *unbiased* manner
so that the expected value of each layer---while fixing
the others---equals the value it would have taken absent noise.
In Bishop's work, he added Gaussian noise
to the inputs to a linear model.
At each training iteration, he added noise
sampled from a distribution with mean zero
$\epsilon \sim \mathcal{N}(0,\sigma^2)$ to the input $\mathbf{x}$,
yielding a perturbed point $\mathbf{x}' = \mathbf{x} + \epsilon$.
In expectation, $E[\mathbf{x}'] = \mathbf{x}$.

In standard dropout regularization,
one zeros out some fraction of the nodes in each layer
and then *debiases* each layer by normalizing
by the fraction of nodes that were retained (not dropped out).
In other words,
with *dropout probability* $p$,
each intermediate activation $h$ is replaced by
a random variable $h'$ as follows:

By design, the expectation remains unchanged, i.e., $E[h'] = h$.

### Dropout in Practice

Recall the MLP with a hidden layer and five hidden units
from .
When we apply dropout to a hidden layer,
zeroing out each hidden unit with probability $p$,
the result can be viewed as a network
containing only a subset of the original neurons.
In , $h_2$ and $h_5$ are removed.
Consequently, the calculation of the outputs
no longer depends on $h_2$ or $h_5$
and their respective gradient also vanishes
when performing backpropagation.
In this way, the calculation of the output layer
cannot be overly dependent on any
one element of $h_1, \ldots, h_5$.

Typically, we disable dropout at test time.
Given a trained model and a new example,
we do not drop out any nodes
and thus do not need to normalize.
However, there are some exceptions:
some researchers use dropout at test time as a heuristic
for estimating the *uncertainty* of neural network predictions:
if the predictions agree across many different dropout outputs,
then we might say that the network is more confident.

### Implementation from Scratch

To implement the dropout function for a single layer,
we must draw as many samples
from a Bernoulli (binary) random variable
as our layer has dimensions,
where the random variable takes value $1$ (keep)
with probability $1-p$ and $0$ (drop) with probability $p$.
One easy way to implement this is to first draw samples
from the uniform distribution $U[0, 1]$.
Then we can keep those nodes for which the corresponding
sample is greater than $p$, dropping the rest.

In the following code, we (**implement a `dropout_layer` function
that drops out the elements in the tensor input `X`
with probability `dropout`**),
rescaling the remainder as described above:
dividing the survivors by `1.0-dropout`.

We can [**test out the `dropout_layer` function on a few examples**].
In the following lines of code,
we pass our input `X` through the dropout operation,
with probabilities 0, 0.5, and 1, respectively.

#### Defining the Model

The model below applies dropout to the output
of each hidden layer (following the activation function).
We can set dropout probabilities for each layer separately.
A common choice is to set
a lower dropout probability closer to the input layer.
We ensure that dropout is only active during training.

#### [**Training**]

The following is similar to the training of MLPs described previously.

### [**Concise Implementation**]

With high-level APIs, all we need to do is add a `Dropout` layer
after each fully connected layer,
passing in the dropout probability
as the only argument to its constructor.
During training, the `Dropout` layer will randomly
drop out outputs of the previous layer
(or equivalently, the inputs to the subsequent layer)
according to the specified dropout probability.
When not in training mode,
the `Dropout` layer simply passes the data through during testing.

Note that we need to redefine the loss function since a network
with a dropout layer needs a PRNGKey when using `Module.apply()`,
and this RNG seed should be explicitly named `dropout`. This key is
used by the `dropout` layer in Flax to generate the random dropout
mask internally. It is important to use a unique `dropout_rng` key
with every epoch in the training loop, otherwise the generated dropout
mask will not be stochastic and different between the epoch runs.
This `dropout_rng` can be stored in the
`TrainState` object (in the `d2l.Trainer` class defined in
it is replaced with a new `dropout_rng`. We already handled this with the
`fit_epoch` method defined in .

Next, we [**train the model**].

### Summary

Beyond controlling the number of dimensions and the size of the weight vector, dropout is yet another tool for avoiding overfitting. Often tools are used jointly.
Note that dropout is
used only during training:
it replaces an activation $h$ with a random variable with expected value $h$.

### Exercises

1. What happens if you change the dropout probabilities for the first and second layers? In particular, what happens if you switch the ones for both layers? Design an experiment to answer these questions, describe your results quantitatively, and summarize the qualitative takeaways.
1. Increase the number of epochs and compare the results obtained when using dropout with those when not using it.
1. What is the variance of the activations in each hidden layer when dropout is and is not applied? Draw a plot to show how this quantity evolves over time for both models.
1. Why is dropout not typically used at test time?
1. Using the model in this section as an example, compare the effects of using dropout and weight decay. What happens when dropout and weight decay are used at the same time? Are the results additive? Are there diminished returns (or worse)? Do they cancel each other out?
1. What happens if we apply dropout to the individual weights of the weight matrix rather than the activations?
1. Invent another technique for injecting random noise at each layer that is different from the standard dropout technique. Can you develop a method that outperforms dropout on the Fashion-MNIST dataset (for a fixed architecture)?

[Discussions](https://discuss.d2l.ai/t/100)

[Discussions](https://discuss.d2l.ai/t/101)

[Discussions](https://discuss.d2l.ai/t/261)

[Discussions](https://discuss.d2l.ai/t/17987)

# Convolutional Neural Networks

Image data is represented as a two-dimensional grid of pixels, be the image
monochromatic or in color. Accordingly each pixel corresponds to one
or multiple numerical values respectively. So far we have ignored this rich
structure and treated images as vectors of numbers by *flattening* them, irrespective of the spatial relation between pixels. This
deeply unsatisfying approach was necessary in order to feed the
resulting one-dimensional vectors through a fully connected MLP.

Because these networks are invariant to the order of the features, we
could get similar results regardless of whether we preserve an order
corresponding to the spatial structure of the pixels or if we permute
the columns of our design matrix before fitting the MLP's parameters.
Ideally, we would leverage our prior knowledge that nearby pixels
are typically related to each other, to build efficient models for
learning from image data.

This chapter introduces *convolutional neural networks* (CNNs)
are designed for precisely this purpose.
CNN-based architectures are
now ubiquitous in the field of computer vision.
For instance, on the Imagnet collection
networks, in short Convnets, that provided significant performance
improvements .

Modern CNNs, as they are called colloquially, owe their design to
inspirations from biology, group theory, and a healthy dose of
experimental tinkering.  In addition to their sample efficiency in
achieving accurate models, CNNs tend to be computationally efficient,
both because they require fewer parameters than fully connected
architectures and because convolutions are easy to parallelize across
GPU cores .  Consequently, practitioners often
apply CNNs whenever possible, and increasingly they have emerged as
credible competitors even on tasks with a one-dimensional sequence
structure, such as audio , text
conventionally used.  Some clever adaptations of CNNs have also
brought them to bear on graph-structured data  and
in recommender systems.

First, we will dive more deeply into the motivation for convolutional
neural networks. This is followed by a walk through the basic operations
that comprise the backbone of all convolutional networks.
These include the convolutional layers themselves,
nitty-gritty details including padding and stride,
the pooling layers used to aggregate information
across adjacent spatial regions,
the use of multiple channels  at each layer,
and a careful discussion of the structure of modern architectures.
We will conclude the chapter with a full working example of LeNet,
the first convolutional network successfully deployed,
long before the rise of modern deep learning.
In the next chapter, we will dive into full implementations
of some popular and comparatively recent CNN architectures
whose designs represent most of the techniques
commonly used by modern practitioners.

## From Fully Connected Layers to Convolutions

To this day,
the models that we have discussed so far
remain appropriate options
when we are dealing with tabular data.
By tabular, we mean that the data consist
of rows corresponding to examples
and columns corresponding to features.
With tabular data, we might anticipate
that the patterns we seek could involve
interactions among the features,
but we do not assume any structure *a priori*
concerning how the features interact.

Sometimes, we truly lack the knowledge to be able to guide the construction of fancier architectures.
In these cases, an MLP
may be the best that we can do.
However, for high-dimensional perceptual data,
such structureless networks can grow unwieldy.

For instance, let's return to our running example
of distinguishing cats from dogs.
Say that we do a thorough job in data collection,
collecting an annotated dataset of one-megapixel photographs.
This means that each input to the network has one million dimensions.
Even an aggressive reduction to one thousand hidden dimensions
would require a fully connected layer
characterized by $10^6 \times 10^3 = 10^9$ parameters.
Unless we have lots of GPUs, a talent
for distributed optimization,
and an extraordinary amount of patience,
learning the parameters of this network
may turn out to be infeasible.

A careful reader might object to this argument
on the basis that one megapixel resolution may not be necessary.
However, while we might be able
to get away with one hundred thousand pixels,
our hidden layer of size 1000 grossly underestimates
the number of hidden units that it takes
to learn good representations of images,
so a practical system will still require billions of parameters.
Moreover, learning a classifier by fitting so many parameters
might require collecting an enormous dataset.
And yet today both humans and computers are able
to distinguish cats from dogs quite well,
seemingly contradicting these intuitions.
That is because images exhibit rich structure
that can be exploited by humans
and machine learning models alike.
Convolutional neural networks (CNNs) are one creative way
that machine learning has embraced for exploiting
some of the known structure in natural images.

### Invariance

Imagine that we want to detect an object in an image.
It seems reasonable that whatever method
we use to recognize objects should not be overly concerned
with the precise location of the object in the image.
Ideally, our system should exploit this knowledge.
Pigs usually do not fly and planes usually do not swim.
Nonetheless, we should still recognize
a pig were one to appear at the top of the image.
We can draw some inspiration here
from the children's game "Where's Waldo"
(which itself has inspired many real-life imitations, such as that depicted in ).
The game consists of a number of chaotic scenes
bursting with activities.
Waldo shows up somewhere in each,
typically lurking in some unlikely location.
The reader's goal is to locate him.
Despite his characteristic outfit,
this can be surprisingly difficult,
due to the large number of distractions.
However, *what Waldo looks like*
does not depend upon *where Waldo is located*.
We could sweep the image with a Waldo detector
that could assign a score to each patch,
indicating the likelihood that the patch contains Waldo.
In fact, many object detection and segmentation algorithms
are based on this approach .
CNNs systematize this idea of *spatial invariance*,
exploiting it to learn useful representations
with fewer parameters.

We can now make these intuitions more concrete
by enumerating a few desiderata to guide our design
of a neural network architecture suitable for computer vision:

1. In the earliest layers, our network
   should respond similarly to the same patch,
   regardless of where it appears in the image. This principle is called *translation invariance* (or *translation equivariance*).
1. The earliest layers of the network should focus on local regions,
   without regard for the contents of the image in distant regions. This is the *locality* principle.
   Eventually, these local representations can be aggregated
   to make predictions at the whole image level.
1. As we proceed, deeper layers should be able to capture longer-range features of the
   image, in a way similar to higher level vision in nature.

Let's see how this translates into mathematics.

### Constraining the MLP

To start off, we can consider an MLP
with two-dimensional images $\mathbf{X}$ as inputs
and their immediate hidden representations
$\mathbf{H}$ similarly represented as matrices (they are two-dimensional tensors in code), where both $\mathbf{X}$ and $\mathbf{H}$ have the same shape.
Let that sink in.
We now imagine that not only the inputs but
also the hidden representations possess spatial structure.

Let $[\mathbf{X}]_{i, j}$ and $[\mathbf{H}]_{i, j}$ denote the pixel
at location $(i,j)$
in the input image and hidden representation, respectively.
Consequently, to have each of the hidden units
receive input from each of the input pixels,
we would switch from using weight matrices
(as we did previously in MLPs)
to representing our parameters
as fourth-order weight tensors $\mathsf{W}$.
Suppose that $\mathbf{U}$ contains biases,
we could formally express the fully connected layer as

This is a *convolution*!
We are effectively weighting pixels at $(i+a, j+b)$
in the vicinity of location $(i, j)$ with coefficients $[\mathbf{V}]_{a, b}$
to obtain the value $[\mathbf{H}]_{i, j}$.
Note that $[\mathbf{V}]_{a, b}$ needs many fewer coefficients than $[\mathsf{V}]_{i, j, a, b}$ since it
no longer depends on the location within the image. Consequently, the number of parameters required is no longer $10^{12}$ but a much more reasonable $4 \times 10^6$: we still have the dependency on $a, b \in (-1000, 1000)$. In short, we have made significant progress. Time-delay neural networks (TDNNs) are some of the first examples to exploit this idea .

####  Locality

Now let's invoke the second principle: locality.
As motivated above, we believe that we should not have
to look very far away from location $(i, j)$
in order to glean relevant information
to assess what is going on at $[\mathbf{H}]_{i, j}$.
This means that outside some range $|a|> \Delta$ or $|b| > \Delta$,
we should set $[\mathbf{V}]_{a, b} = 0$.
Equivalently, we can rewrite $[\mathbf{H}]_{i, j}$ as

That is, we measure the overlap between $f$ and $g$
when one function is "flipped" and shifted by $\mathbf{x}$.
Whenever we have discrete objects, the integral turns into a sum.
For instance, for vectors from
the set of square-summable infinite-dimensional vectors
with index running over $\mathbb{Z}$ we obtain the following definition:

This looks similar to , with one major difference.
Rather than using $(i+a, j+b)$, we are using the difference instead.
Note, though, that this distinction is mostly cosmetic
since we can always match the notation between
Our original definition in  more properly
describes a *cross-correlation*.
We will come back to this in the following section.

### Channels

Returning to our Waldo detector, let's see what this looks like.
The convolutional layer picks windows of a given size
and weighs intensities according to the filter $\mathsf{V}$, as demonstrated in .
We might aim to learn a model so that
wherever the "waldoness" is highest,
we should find a peak in the hidden layer representations.

There is just one problem with this approach.
So far, we blissfully ignored that images consist
of three channels: red, green, and blue.
In sum, images are not two-dimensional objects
but rather third-order tensors,
characterized by a height, width, and channel,
e.g., with shape $1024 \times 1024 \times 3$ pixels.
While the first two of these axes concern spatial relationships,
the third can be regarded as assigning
a multidimensional representation to each pixel location.
We thus index $\mathsf{X}$ as $[\mathsf{X}]_{i, j, k}$.
The convolutional filter has to adapt accordingly.
Instead of $[\mathbf{V}]_{a,b}$, we now have $[\mathsf{V}]_{a,b,c}$.

Moreover, just as our input consists of a third-order tensor,
it turns out to be a good idea to similarly formulate
our hidden representations as third-order tensors $\mathsf{H}$.
In other words, rather than just having a single hidden representation
corresponding to each spatial location,
we want an entire vector of hidden representations
corresponding to each spatial location.
We could think of the hidden representations as comprising
a number of two-dimensional grids stacked on top of each other.
As in the inputs, these are sometimes called *channels*.
They are also sometimes called *feature maps*,
as each provides a spatialized set
of learned features for the subsequent layer.
Intuitively, you might imagine that at lower layers that are closer to inputs,
some channels could become specialized to recognize edges while
others could recognize textures.

To support multiple channels in both inputs ($\mathsf{X}$) and hidden representations ($\mathsf{H}$),
we can add a fourth coordinate to $\mathsf{V}$: $[\mathsf{V}]_{a, b, c, d}$.
Putting everything together we have:

## Convolutions for Images

Now that we understand how convolutional layers work in theory,
we are ready to see how they work in practice.
Building on our motivation of convolutional neural networks
as efficient architectures for exploring structure in image data,
we stick with images as our running example.

### The Cross-Correlation Operation

Recall that strictly speaking, convolutional layers
are a  misnomer, since the operations they express
are more accurately described as cross-correlations.
Based on our descriptions of convolutional layers in ,
in such a layer, an input tensor
and a kernel tensor are combined
to produce an output tensor through a (**cross-correlation operation.**)

Let's ignore channels for now and see how this works
with two-dimensional data and hidden representations.
In ,
the input is a two-dimensional tensor
with a height of 3 and width of 3.
We mark the shape of the tensor as $3 \times 3$ or ($3$, $3$).
The height and width of the kernel are both 2.
The shape of the *kernel window* (or *convolution window*)
is given by the height and width of the kernel
(here it is $2 \times 2$).

In the two-dimensional cross-correlation operation,
we begin with the convolution window positioned
at the upper-left corner of the input tensor
and slide it across the input tensor,
both from left to right and top to bottom.
When the convolution window slides to a certain position,
the input subtensor contained in that window
and the kernel tensor are multiplied elementwise
and the resulting tensor is summed up
yielding a single scalar value.
This result gives the value of the output tensor
at the corresponding location.
Here, the output tensor has a height of 2 and width of 2
and the four elements are derived from
the two-dimensional cross-correlation operation:

Note that along each axis, the output size
is slightly smaller than the input size.
Because the kernel has width and height greater than $1$,
we can only properly compute the cross-correlation
for locations where the kernel fits wholly within the image,
the output size is given by the input size $n_\textrm{h} \times n_\textrm{w}$
minus the size of the convolution kernel $k_\textrm{h} \times k_\textrm{w}$
via

## Padding and Stride

Recall the example of a convolution in .
The input had both a height and width of 3
and the convolution kernel had both a height and width of 2,
yielding an output representation with dimension $2\times2$.
Assuming that the input shape is $n_\textrm{h}\times n_\textrm{w}$
and the convolution kernel shape is $k_\textrm{h}\times k_\textrm{w}$,
the output shape will be $(n_\textrm{h}-k_\textrm{h}+1) \times (n_\textrm{w}-k_\textrm{w}+1)$:
we can only shift the convolution kernel so far until it runs out
of pixels to apply the convolution to.

In the following we will explore a number of techniques,
including padding and strided convolutions,
that offer more control over the size of the output.
As motivation, note that since kernels generally
have width and height greater than $1$,
after applying many successive convolutions,
we tend to wind up with outputs that are
considerably smaller than our input.
If we start with a $240 \times 240$ pixel image,
ten layers of $5 \times 5$ convolutions
reduce the image to $200 \times 200$ pixels,
slicing off $30 \%$ of the image and with it
obliterating any interesting information
on the boundaries of the original image.
*Padding* is the most popular tool for handling this issue.
In other cases, we may want to reduce the dimensionality drastically,
e.g., if we find the original input resolution to be unwieldy.
*Strided convolutions* are a popular technique that can help in these instances.

### Padding

As described above, one tricky issue when applying convolutional layers
is that we tend to lose pixels on the perimeter of our image. Consider  that depicts the pixel utilization as a function of the convolution kernel size and the position within the image. The pixels in the corners are hardly used at all.

Since we typically use small kernels,
for any given convolution
we might only lose a few pixels
but this can add up as we apply
many successive convolutional layers.
One straightforward solution to this problem
is to add extra pixels of filler around the boundary of our input image,
thus increasing the effective size of the image.
Typically, we set the values of the extra pixels to zero.
In , we pad a $3 \times 3$ input,
increasing its size to $5 \times 5$.
The corresponding output then increases to a $4 \times 4$ matrix.
The shaded portions are the first output element as well as the input and kernel tensor elements used for the output computation: $0\times0+0\times1+0\times2+0\times3=0$.

In general, if we add a total of $p_\textrm{h}$ rows of padding
(roughly half on top and half on bottom)
and a total of $p_\textrm{w}$ columns of padding
(roughly half on the left and half on the right),
the output shape will be

If we set $p_\textrm{h}=k_\textrm{h}-1$ and $p_\textrm{w}=k_\textrm{w}-1$,
then the output shape can be simplified to
$\lfloor(n_\textrm{h}+s_\textrm{h}-1)/s_\textrm{h}\rfloor \times \lfloor(n_\textrm{w}+s_\textrm{w}-1)/s_\textrm{w}\rfloor$.
Going a step further, if the input height and width
are divisible by the strides on the height and width,
then the output shape will be $(n_\textrm{h}/s_\textrm{h}) \times (n_\textrm{w}/s_\textrm{w})$.

Below, we [**set the strides on both the height and width to 2**],
thus halving the input height and width.

Let's look at (**a slightly more complicated example**).

### Summary and Discussion

Padding can increase the height and width of the output. This is often used to give the output the same height and width as the input to avoid undesirable shrinkage of the output. Moreover, it ensures that all pixels are used equally frequently. Typically we pick symmetric padding on both sides of the input height and width. In this case we refer to $(p_\textrm{h}, p_\textrm{w})$ padding. Most commonly we set $p_\textrm{h} = p_\textrm{w}$, in which case we simply state that we choose padding $p$.

A similar convention applies to strides. When horizontal stride $s_\textrm{h}$ and vertical stride $s_\textrm{w}$ match, we simply talk about stride $s$. The stride can reduce the resolution of the output, for example reducing the height and width of the output to only $1/n$ of the height and width of the input for $n > 1$. By default, the padding is 0 and the stride is 1.

So far all padding that we discussed simply extended images with zeros. This has significant computational benefit since it is trivial to accomplish. Moreover, operators can be engineered to take advantage of this padding implicitly without the need to allocate additional memory. At the same time, it allows CNNs to encode implicit position information within an image, simply by learning where the "whitespace" is. There are many alternatives to zero-padding.  provided an extensive overview of those (albeit without a clear case for when to use nonzero paddings unless artifacts occur).

### Exercises

1. Given the final code example in this section with kernel size $(3, 5)$, padding $(0, 1)$, and stride $(3, 4)$,
   calculate the output shape to check if it is consistent with the experimental result.
1. For audio signals, what does a stride of 2 correspond to?
1. Implement mirror padding, i.e., padding where the border values are simply mirrored to extend tensors.
1. What are the computational benefits of a stride larger than 1?
1. What might be statistical benefits of a stride larger than 1?
1. How would you implement a stride of $\frac{1}{2}$? What does it correspond to? When would this be useful?

[Discussions](https://discuss.d2l.ai/t/67)

[Discussions](https://discuss.d2l.ai/t/68)

[Discussions](https://discuss.d2l.ai/t/272)

[Discussions](https://discuss.d2l.ai/t/17997)

## Multiple Input and Multiple Output Channels

While we described the multiple channels
that comprise each image (e.g., color images have the standard RGB channels
to indicate the amount of red, green and blue) and convolutional layers for multiple channels in ,
until now, we simplified all of our numerical examples
by working with just a single input and a single output channel.
This allowed us to think of our inputs, convolution kernels,
and outputs each as two-dimensional tensors.

When we add channels into the mix,
our inputs and hidden representations
both become three-dimensional tensors.
For example, each RGB input image has shape $3\times h\times w$.
We refer to this axis, with a size of 3, as the *channel* dimension. The notion of
channels is as old as CNNs themselves: for instance LeNet-5  uses them.
In this section, we will take a deeper look
at convolution kernels with multiple input and multiple output channels.

### Multiple Input Channels

When the input data contains multiple channels,
we need to construct a convolution kernel
with the same number of input channels as the input data,
so that it can perform cross-correlation with the input data.
Assuming that the number of channels for the input data is $c_\textrm{i}$,
the number of input channels of the convolution kernel also needs to be $c_\textrm{i}$. If our convolution kernel's window shape is $k_\textrm{h}\times k_\textrm{w}$,
then, when $c_\textrm{i}=1$, we can think of our convolution kernel
as just a two-dimensional tensor of shape $k_\textrm{h}\times k_\textrm{w}$.

However, when $c_\textrm{i}>1$, we need a kernel
that contains a tensor of shape $k_\textrm{h}\times k_\textrm{w}$ for *every* input channel. Concatenating these $c_\textrm{i}$ tensors together
yields a convolution kernel of shape $c_\textrm{i}\times k_\textrm{h}\times k_\textrm{w}$.
Since the input and convolution kernel each have $c_\textrm{i}$ channels,
we can perform a cross-correlation operation
on the two-dimensional tensor of the input
and the two-dimensional tensor of the convolution kernel
for each channel, adding the $c_\textrm{i}$ results together
(summing over the channels)
to yield a two-dimensional tensor.
This is the result of a two-dimensional cross-correlation
between a multi-channel input and
a multi-input-channel convolution kernel.

of a two-dimensional cross-correlation with two input channels.
The shaded portions are the first output element
as well as the input and kernel tensor elements used for the output computation:
$(1\times1+2\times2+4\times3+5\times4)+(0\times0+1\times1+3\times2+4\times3)=56$.

To make sure we really understand what is going on here,
we can (**implement cross-correlation operations with multiple input channels**) ourselves.
Notice that all we are doing is performing a cross-correlation operation
per channel and then adding up the results.

We can construct the input tensor `X` and the kernel tensor `K`
corresponding to the values in
to (**validate the output**) of the cross-correlation operation.

### Multiple Output Channels

Regardless of the number of input channels,
so far we always ended up with one output channel.
However, as we discussed in ,
it turns out to be essential to have multiple channels at each layer.
In the most popular neural network architectures,
we actually increase the channel dimension
as we go deeper in the neural network,
typically downsampling to trade off spatial resolution
for greater *channel depth*.
Intuitively, you could think of each channel
as responding to a different set of features.
The reality is a bit more complicated than this. A naive interpretation would suggest
that representations are learned independently per pixel or per channel.
Instead, channels are optimized to be jointly useful.
This means that rather than mapping a single channel to an edge detector, it may simply mean
that some direction in channel space corresponds to detecting edges.

Denote by $c_\textrm{i}$ and $c_\textrm{o}$ the number
of input and output channels, respectively,
and by $k_\textrm{h}$ and $k_\textrm{w}$ the height and width of the kernel.
To get an output with multiple channels,
we can create a kernel tensor
of shape $c_\textrm{i}\times k_\textrm{h}\times k_\textrm{w}$
for *every* output channel.
We concatenate them on the output channel dimension,
so that the shape of the convolution kernel
is $c_\textrm{o}\times c_\textrm{i}\times k_\textrm{h}\times k_\textrm{w}$.
In cross-correlation operations,
the result on each output channel is calculated
from the convolution kernel corresponding to that output channel
and takes input from all channels in the input tensor.

We implement a cross-correlation function
to [**calculate the output of multiple channels**] as shown below.

We construct a trivial convolution kernel with three output channels
by concatenating the kernel tensor for `K` with `K+1` and `K+2`.

Below, we perform cross-correlation operations
on the input tensor `X` with the kernel tensor `K`.
Now the output contains three channels.
The result of the first channel is consistent
with the result of the previous input tensor `X`
and the multi-input channel,
single-output channel kernel.

### $1\times 1$ Convolutional Layer

At first, a [**$1 \times 1$ convolution**], i.e., $k_\textrm{h} = k_\textrm{w} = 1$,
does not seem to make much sense.
After all, a convolution correlates adjacent pixels.
A $1 \times 1$ convolution obviously does not.
Nonetheless, they are popular operations that are sometimes included
in the designs of complex deep networks .
Let's see in some detail what it actually does.

Because the minimum window is used,
the $1\times 1$ convolution loses the ability
of larger convolutional layers
to recognize patterns consisting of interactions
among adjacent elements in the height and width dimensions.
The only computation of the $1\times 1$ convolution occurs
on the channel dimension.

using the $1\times 1$ convolution kernel
with 3 input channels and 2 output channels.
Note that the inputs and outputs have the same height and width.
Each element in the output is derived
from a linear combination of elements *at the same position*
in the input image.
You could think of the $1\times 1$ convolutional layer
as constituting a fully connected layer applied at every single pixel location
to transform the $c_\textrm{i}$ corresponding input values into $c_\textrm{o}$ output values.
Because this is still a convolutional layer,
the weights are tied across pixel location.
Thus the $1\times 1$ convolutional layer requires $c_\textrm{o}\times c_\textrm{i}$ weights
(plus the bias). Also note that convolutional layers are typically followed
by nonlinearities. This ensures that $1 \times 1$ convolutions cannot simply be
folded into other convolutions.

Let's check whether this works in practice:
we implement a $1 \times 1$ convolution
using a fully connected layer.
The only thing is that we need to make some adjustments
to the data shape before and after the matrix multiplication.

When performing $1\times 1$ convolutions,
the above function is equivalent to the previously implemented cross-correlation function `corr2d_multi_in_out`.
Let's check this with some sample data.

### Discussion

Channels allow us to combine the best of both worlds: MLPs that allow for significant nonlinearities and convolutions that allow for *localized* analysis of features. In particular, channels allow the CNN to reason with multiple features, such as edge and shape detectors at the same time. They also offer a practical trade-off between the drastic parameter reduction arising from translation invariance and locality, and the need for expressive and diverse models in computer vision.

Note, though, that this flexibility comes at a price. Given an image of size $(h \times w)$, the cost for computing a $k \times k$ convolution is $\mathcal{O}(h \cdot w \cdot k^2)$. For $c_\textrm{i}$ and $c_\textrm{o}$ input and output channels respectively this increases to $\mathcal{O}(h \cdot w \cdot k^2 \cdot c_\textrm{i} \cdot c_\textrm{o})$. For a $256 \times 256$ pixel image with a $5 \times 5$ kernel and $128$ input and output channels respectively this amounts to over 53 billion operations (we count multiplications and additions separately). Later on we will encounter effective strategies to cut down on the cost, e.g., by requiring the channel-wise operations to be block-diagonal, leading to architectures such as ResNeXt .

### Exercises

1. Assume that we have two convolution kernels of size $k_1$ and $k_2$, respectively
   (with no nonlinearity in between).
    1. Prove that the result of the operation can be expressed by a single convolution.
    1. What is the dimensionality of the equivalent single convolution?
    1. Is the converse true, i.e., can you always decompose a convolution into two smaller ones?
1. Assume an input of shape $c_\textrm{i}\times h\times w$ and a convolution kernel of shape
   $c_\textrm{o}\times c_\textrm{i}\times k_\textrm{h}\times k_\textrm{w}$, padding of $(p_\textrm{h}, p_\textrm{w})$, and stride of $(s_\textrm{h}, s_\textrm{w})$.
    1. What is the computational cost (multiplications and additions) for the forward propagation?
    1. What is the memory footprint?
    1. What is the memory footprint for the backward computation?
    1. What is the computational cost for the backpropagation?
1. By what factor does the number of calculations increase if we double both the number of input channels
   $c_\textrm{i}$ and the number of output channels $c_\textrm{o}$? What happens if we double the padding?
1. Are the variables `Y1` and `Y2` in the final example of this section exactly the same? Why?
1. Express convolutions as a matrix multiplication, even when the convolution window is not $1 \times 1$.
1. Your task is to implement fast convolutions with a $k \times k$ kernel. One of the algorithm candidates
   is to scan horizontally across the source, reading a $k$-wide strip and computing the $1$-wide output strip
   one value at a time. The alternative is to read a $k + \Delta$ wide strip and compute a $\Delta$-wide
   output strip. Why is the latter preferable? Is there a limit to how large you should choose $\Delta$?
1. Assume that we have a $c \times c$ matrix.
    1. How much faster is it to multiply with a block-diagonal matrix if the matrix is broken up into $b$ blocks?
    1. What is the downside of having $b$ blocks? How could you fix it, at least partly?

[Discussions](https://discuss.d2l.ai/t/69)

[Discussions](https://discuss.d2l.ai/t/70)

[Discussions](https://discuss.d2l.ai/t/273)

[Discussions](https://discuss.d2l.ai/t/17998)

## Pooling

In many cases our ultimate task asks some global question about the image,
e.g., *does it contain a cat?* Consequently, the units of our final layer
should be sensitive to the entire input.
By gradually aggregating information, yielding coarser and coarser maps,
we accomplish this goal of ultimately learning a global representation,
while keeping all of the advantages of convolutional layers at the intermediate layers of processing.
The deeper we go in the network,
the larger the receptive field (relative to the input)
to which each hidden node is sensitive. Reducing spatial resolution
accelerates this process,
since the convolution kernels cover a larger effective area.

Moreover, when detecting lower-level features, such as edges
(as discussed in ),
we often want our representations to be somewhat invariant to translation.
For instance, if we take the image `X`
with a sharp delineation between black and white
and shift the whole image by one pixel to the right,
i.e., `Z[i, j] = X[i, j + 1]`,
then the output for the new image `Z` might be vastly different.
The edge will have shifted by one pixel.
In reality, objects hardly ever occur exactly at the same place.
In fact, even with a tripod and a stationary object,
vibration of the camera due to the movement of the shutter
might shift everything by a pixel or so
(high-end cameras are loaded with special features to address this problem).

This section introduces *pooling layers*,
which serve the dual purposes of
mitigating the sensitivity of convolutional layers to location
and of spatially downsampling representations.

### Maximum Pooling and Average Pooling

Like convolutional layers, *pooling* operators
consist of a fixed-shape window that is slid over
all regions in the input according to its stride,
computing a single output for each location traversed
by the fixed-shape window (sometimes known as the *pooling window*).
However, unlike the cross-correlation computation
of the inputs and kernels in the convolutional layer,
the pooling layer contains no parameters (there is no *kernel*).
Instead, pooling operators are deterministic,
typically calculating either the maximum or the average value
of the elements in the pooling window.
These operations are called *maximum pooling* (*max-pooling* for short)
and *average pooling*, respectively.

*Average pooling* is essentially as old as CNNs. The idea is akin to
downsampling an image. Rather than just taking the value of every second (or third)
pixel for the lower resolution image, we can average over adjacent pixels to obtain
an image with better signal-to-noise ratio since we are combining the information
from multiple adjacent pixels. *Max-pooling* was introduced in
how information aggregation might be aggregated hierarchically for the purpose
of object recognition; there already was an earlier version in speech recognition . In almost all cases, max-pooling, as it is also referred to,
is preferable to average pooling.

In both cases, as with the cross-correlation operator,
we can think of the pooling window
as starting from the upper-left of the input tensor
and sliding across it from left to right and top to bottom.
At each location that the pooling window hits,
it computes the maximum or average
value of the input subtensor in the window,
depending on whether max or average pooling is employed.

The output tensor in   has a height of 2 and a width of 2.
The four elements are derived from the maximum value in each pooling window:

More generally, we can define a $p \times q$ pooling layer by aggregating over
a region of said size. Returning to the problem of edge detection,
we use the output of the convolutional layer
as input for $2\times 2$ max-pooling.
Denote by `X` the input of the convolutional layer input and `Y` the pooling layer output.
Regardless of whether or not the values of `X[i, j]`, `X[i, j + 1]`,
`X[i+1, j]` and `X[i+1, j + 1]` are different,
the pooling layer always outputs `Y[i, j] = 1`.
That is to say, using the $2\times 2$ max-pooling layer,
we can still detect if the pattern recognized by the convolutional layer
moves no more than one element in height or width.

In the code below, we (**implement the forward propagation
of the pooling layer**) in the `pool2d` function.
This function is similar to the `corr2d` function
in .
However, no kernel is needed, computing the output
as either the maximum or the average of each region in the input.

We can construct the input tensor `X` in  to [**validate the output of the two-dimensional max-pooling layer**].

Also, we can experiment with (**the average pooling layer**).

### [**Padding and Stride**]

As with convolutional layers, pooling layers
change the output shape.
And as before, we can adjust the operation to achieve a desired output shape
by padding the input and adjusting the stride.
We can demonstrate the use of padding and strides
in pooling layers via the built-in two-dimensional max-pooling layer from the deep learning framework.
We first construct an input tensor `X` whose shape has four dimensions,
where the number of examples (batch size) and number of channels are both 1.

Note that unlike other frameworks, TensorFlow
prefers and is optimized for *channels-last* input.

Since pooling aggregates information from an area, (**deep learning frameworks default to matching pooling window sizes and stride.**) For instance, if we use a pooling window of shape `(3, 3)`
we get a stride shape of `(3, 3)` by default.

Needless to say, [**the stride and padding can be manually specified**] to override framework defaults if required.

Of course, we can specify an arbitrary rectangular pooling window with arbitrary height and width respectively, as the example below shows.

### Multiple Channels

When processing multi-channel input data,
[**the pooling layer pools each input channel separately**],
rather than summing the inputs up over channels
as in a convolutional layer.
This means that the number of output channels for the pooling layer
is the same as the number of input channels.
Below, we will concatenate tensors `X` and `X + 1`
on the channel dimension to construct an input with two channels.

Note that this will require a
concatenation along the last dimension for TensorFlow due to the channels-last syntax.

As we can see, the number of output channels is still two after pooling.

Note that the output for the TensorFlow pooling appears at first glance to be different, however
numerically the same results are presented as MXNet and PyTorch.
The difference lies in the dimensionality, and reading the
output vertically yields the same output as the other implementations.

### Summary

Pooling is an exceedingly simple operation. It does exactly what its name indicates, aggregate results over a window of values. All convolution semantics, such as strides and padding apply in the same way as they did previously. Note that pooling is indifferent to channels, i.e., it leaves the number of channels unchanged and it applies to each channel separately. Lastly, of the two popular pooling choices, max-pooling is preferable to average pooling, as it confers some degree of invariance to output. A popular choice is to pick a pooling window size of $2 \times 2$ to quarter the spatial resolution of output.

Note that there are many more ways of reducing resolution beyond pooling. For instance, in stochastic pooling  and fractional max-pooling  aggregation is combined with randomization. This can slightly improve the accuracy in some cases. Lastly, as we will see later with the attention mechanism, there are more refined ways of aggregating over outputs, e.g., by using the alignment between a query and representation vectors.

### Exercises

1. Implement average pooling through a convolution.
1. Prove that max-pooling cannot be implemented through a convolution alone.
1. Max-pooling can be accomplished using ReLU operations, i.e., $\textrm{ReLU}(x) = \max(0, x)$.
    1. Express $\max (a, b)$ by using only ReLU operations.
    1. Use this to implement max-pooling by means of convolutions and ReLU layers.
    1. How many channels and layers do you need for a $2 \times 2$ convolution? How many for a $3 \times 3$ convolution?
1. What is the computational cost of the pooling layer? Assume that the input to the pooling layer is of size $c\times h\times w$, the pooling window has a shape of $p_\textrm{h}\times p_\textrm{w}$ with a padding of $(p_\textrm{h}, p_\textrm{w})$ and a stride of $(s_\textrm{h}, s_\textrm{w})$.
1. Why do you expect max-pooling and average pooling to work differently?
1. Do we need a separate minimum pooling layer? Can you replace it with another operation?
1. We could use the softmax operation for pooling. Why might it not be so popular?

[Discussions](https://discuss.d2l.ai/t/71)

[Discussions](https://discuss.d2l.ai/t/72)

[Discussions](https://discuss.d2l.ai/t/274)

[Discussions](https://discuss.d2l.ai/t/17999)

## Convolutional Neural Networks (LeNet)

We now have all the ingredients required to assemble
a fully-functional CNN.
In our earlier encounter with image data, we applied
a linear model with softmax regression ()
and an MLP ()
to pictures of clothing in the Fashion-MNIST dataset.
To make such data amenable we first flattened each image from a $28\times28$ matrix
into a fixed-length $784$-dimensional vector,
and thereafter processed them in fully connected layers.
Now that we have a handle on convolutional layers,
we can retain the spatial structure in our images.
As an additional benefit of replacing fully connected layers with convolutional layers,
we will enjoy more parsimonious models that require far fewer parameters.

In this section, we will introduce *LeNet*,
among the first published CNNs
to capture wide attention for its performance on computer vision tasks.
The model was introduced by (and named for) Yann LeCun,
then a researcher at AT&T Bell Labs,
for the purpose of recognizing handwritten digits in images .
This work represented the culmination
of a decade of research developing the technology;
LeCun's team published the first study to successfully
train CNNs via backpropagation .

At the time LeNet achieved outstanding results
matching the performance of support vector machines,
then a dominant approach in supervised learning, achieving an error rate of less than 1% per digit.
LeNet was eventually adapted to recognize digits
for processing deposits in ATM machines.
To this day, some ATMs still run the code
that Yann LeCun and his colleague Leon Bottou wrote in the 1990s!

### LeNet

At a high level, (**LeNet (LeNet-5) consists of two parts:
(i) a convolutional encoder consisting of two convolutional layers; and
(ii) a dense block consisting of three fully connected layers**).
The architecture is summarized in .

The basic units in each convolutional block
are a convolutional layer, a sigmoid activation function,
and a subsequent average pooling operation.
Note that while ReLUs and max-pooling work better,
they had not yet been discovered.
Each convolutional layer uses a $5\times 5$ kernel
and a sigmoid activation function.
These layers map spatially arranged inputs
to a number of two-dimensional feature maps, typically
increasing the number of channels.
The first convolutional layer has 6 output channels,
while the second has 16.
Each $2\times2$ pooling operation (stride 2)
reduces dimensionality by a factor of $4$ via spatial downsampling.
The convolutional block emits an output with shape given by
(batch size, number of channel, height, width).

In order to pass output from the convolutional block
to the dense block,
we must flatten each example in the minibatch.
In other words, we take this four-dimensional input and transform it
into the two-dimensional input expected by fully connected layers:
as a reminder, the two-dimensional representation that we desire uses the first dimension to index examples in the minibatch
and the second to give the flat vector representation of each example.
LeNet's dense block has three fully connected layers,
with 120, 84, and 10 outputs, respectively.
Because we are still performing classification,
the 10-dimensional output layer corresponds
to the number of possible output classes.

While getting to the point where you truly understand
what is going on inside LeNet may have taken a bit of work,
we hope that the following code snippet will convince you
that implementing such models with modern deep learning frameworks
is remarkably simple.
We need only to instantiate a `Sequential` block
and chain together the appropriate layers,
using Xavier initialization as
introduced in .

We have taken some liberty in the reproduction of LeNet insofar as we have replaced the Gaussian activation layer by
a softmax layer. This greatly simplifies the implementation, not least due to the
fact that the Gaussian decoder is rarely used nowadays. Other than that, this network matches
the original LeNet-5 architecture.

Let's see what happens inside the network. By passing a
single-channel (black and white)
$28 \times 28$ image through the network
and printing the output shape at each layer,
we can [**inspect the model**] to ensure
that its operations line up with
what we expect from .

Let's see what happens inside the network. By passing a
single-channel (black and white)
$28 \times 28$ image through the network
and printing the output shape at each layer,
we can [**inspect the model**] to ensure
that its operations line up with
what we expect from .
Flax provides `nn.tabulate`, a nifty method to summarise the layers and
parameters in our network. Here we use the `bind` method to create a bounded model.
The variables are now bound to the `d2l.Module` class, i.e., this bounded model
becomes a stateful object which can then be used to access the `Sequential`
object attribute `net` and the `layers` within. Note that the `bind` method should
only be used for interactive experimentation, and is not a direct
replacement for the `apply` method.

Note that the height and width of the representation
at each layer throughout the convolutional block
is reduced (compared with the previous layer).
The first convolutional layer uses two pixels of padding
to compensate for the reduction in height and width
that would otherwise result from using a $5 \times 5$ kernel.
As an aside, the image size of $28 \times 28$ pixels in the original
MNIST OCR dataset is a result of *trimming* two pixel rows (and columns) from the
original scans that measured $32 \times 32$ pixels. This was done primarily to
save space (a 30% reduction) at a time when megabytes mattered.

In contrast, the second convolutional layer forgoes padding,
and thus the height and width are both reduced by four pixels.
As we go up the stack of layers,
the number of channels increases layer-over-layer
from 1 in the input to 6 after the first convolutional layer
and 16 after the second convolutional layer.
However, each pooling layer halves the height and width.
Finally, each fully connected layer reduces dimensionality,
finally emitting an output whose dimension
matches the number of classes.

### Training

Now that we have implemented the model,
let's [**run an experiment to see how the LeNet-5 model fares on Fashion-MNIST**].

While CNNs have fewer parameters,
they can still be more expensive to compute
than similarly deep MLPs
because each parameter participates in many more
multiplications.
If you have access to a GPU, this might be a good time
to put it into action to speed up training.
Note that
the `d2l.Trainer` class takes care of all details.
By default, it initializes the model parameters on the
available devices.
Just as with MLPs, our loss function is cross-entropy,
and we minimize it via minibatch stochastic gradient descent.

### Summary

We have made significant progress in this chapter. We moved from the MLPs of the 1980s to the CNNs of the 1990s and early 2000s. The architectures proposed, e.g., in the form of LeNet-5 remain meaningful, even to this day. It is worth comparing the error rates on Fashion-MNIST achievable with LeNet-5 both to the very best possible with MLPs () and those with significantly more advanced architectures such as ResNet (). LeNet is much more similar to the latter than to the former. One of the primary differences, as we shall see, is that greater amounts of computation enabled significantly more complex architectures.

A second difference is the relative ease with which we were able to implement LeNet. What used to be an engineering challenge worth months of C++ and assembly code, engineering to improve SN, an early Lisp-based deep learning tool , and finally experimentation with models can now be accomplished in minutes. It is this incredible productivity boost that has democratized deep learning model development tremendously. In the next chapter, we will journey down this rabbit hole to see where it takes us.

### Exercises

1. Let's modernize LeNet. Implement and test the following changes:
    1. Replace average pooling with max-pooling.
    1. Replace the softmax layer with ReLU.
1. Try to change the size of the LeNet style network to improve its accuracy in addition to max-pooling and ReLU.
    1. Adjust the convolution window size.
    1. Adjust the number of output channels.
    1. Adjust the number of convolution layers.
    1. Adjust the number of fully connected layers.
    1. Adjust the learning rates and other training details (e.g., initialization and number of epochs).
1. Try out the improved network on the original MNIST dataset.
1. Display the activations of the first and second layer of LeNet for different inputs (e.g., sweaters and coats).
1. What happens to the activations when you feed significantly different images into the network (e.g., cats, cars, or even random noise)?

[Discussions](https://discuss.d2l.ai/t/73)

[Discussions](https://discuss.d2l.ai/t/74)

[Discussions](https://discuss.d2l.ai/t/275)

[Discussions](https://discuss.d2l.ai/t/18000)

# Recurrent Neural Networks

Up until now, we have focused primarily on fixed-length data.
When introducing linear and logistic regression
in  and
and multilayer perceptrons in ,
we were happy to assume that each feature vector $\mathbf{x}_i$
consisted of a fixed number of components $x_1, \dots, x_d$,
where each numerical feature $x_j$
corresponded to a particular attribute.
These datasets are sometimes called *tabular*,
because they can be arranged in tables,
where each example $i$ gets its own row,
and each attribute gets its own column.
Crucially, with tabular data, we seldom
assume any particular structure over the columns.

Subsequently, in ,
we moved on to image data, where inputs consist
of the raw pixel values at each coordinate in an image.
Image data hardly fitted the bill
of a protypical tabular dataset.
There, we needed to call upon convolutional neural networks (CNNs)
to handle the hierarchical structure and invariances.
However, our data were still of fixed length.
Every Fashion-MNIST image is represented
as a $28 \times 28$ grid of pixel values.
Moreover, our goal was to develop a model
that looked at just one image and then
outputted a single prediction.
But what should we do when faced with a
sequence of images, as in a video,
or when tasked with producing
a sequentially structured prediction,
as in the case of image captioning?

A great many learning tasks require dealing with sequential data.
Image captioning, speech synthesis, and music generation
all require that models produce outputs consisting of sequences.
In other domains, such as time series prediction,
video analysis, and musical information retrieval,
a model must learn from inputs that are sequences.
These demands often arise simultaneously:
tasks such as translating passages of text
from one natural language to another,
engaging in dialogue, or controlling a robot,
demand that models both ingest and output
sequentially structured data.

Recurrent neural networks (RNNs) are deep learning models
that capture the dynamics of sequences via
*recurrent* connections, which can be thought of
as cycles in the network of nodes.
This might seem counterintuitive at first.
After all, it is the feedforward nature of neural networks
that makes the order of computation unambiguous.
However, recurrent edges are defined in a precise way
that ensures that no such ambiguity can arise.
Recurrent neural networks are *unrolled* across time steps (or sequence steps),
with the *same* underlying parameters applied at each step.
While the standard connections are applied *synchronously*
to propagate each layer's activations
to the subsequent layer *at the same time step*,
the recurrent connections are *dynamic*,
passing information across adjacent time steps.
As the unfolded view in  reveals,
RNNs can be thought of as feedforward neural networks
where each layer's parameters (both conventional and recurrent)
are shared across time steps.

Like neural networks more broadly,
RNNs have a long discipline-spanning history,
originating as models of the brain popularized
by cognitive scientists and subsequently adopted
as practical modeling tools employed
by the machine learning community.
As we do for deep learning more broadly,
in this book we adopt the machine learning perspective,
focusing on RNNs as practical tools that rose
to popularity in the 2010s owing to
breakthrough results on such diverse tasks
as handwriting recognition ,
machine translation ,
and recognizing medical diagnoses .
We point the reader interested in more
background material to a publicly available
comprehensive review .
We also note that sequentiality is not unique to RNNs.
For example, the CNNs that we already introduced
can be adapted to handle data of varying length,
e.g., images of varying resolution.
Moreover, RNNs have recently ceded considerable
market share to Transformer models,
which will be covered in .
However, RNNs rose to prominence as the default models
for handling complex sequential structure in deep learning,
and remain staple models for sequential modeling to this day.
The stories of RNNs and of sequence modeling
are inextricably linked, and this is as much
a chapter about the ABCs of sequence modeling problems
as it is a chapter about RNNs.

One key insight paved the way for a revolution in sequence modeling.
While the inputs and targets for many fundamental tasks in machine learning
cannot easily be represented as fixed-length vectors,
they can often nevertheless be represented as
varying-length sequences of fixed-length vectors.
For example, documents can be represented as sequences of words;
medical records can often be represented as sequences of events
(encounters, medications, procedures, lab tests, diagnoses);
videos can be represented as varying-length sequences of still images.

While sequence models have popped up in numerous application areas,
basic research in the area has been driven predominantly
by advances on core tasks in natural language processing.
Thus, throughout this chapter, we will focus
our exposition and examples on text data.
If you get the hang of these examples,
then applying the models to other data modalities
should be relatively straightforward.
In the next few sections, we introduce basic
notation for sequences and some evaluation measures
for assessing the quality of sequentially structured model outputs.
After that, we discuss basic concepts of a language model
and use this discussion to motivate our first RNN models.
Finally, we describe the method for calculating gradients
when backpropagating through RNNs and explore some challenges
that are often encountered when training such networks,
motivating the modern RNN architectures that will follow
in .

## Working with Sequences

Up until now, we have focused on models whose inputs
consisted of a single feature vector $\mathbf{x} \in \mathbb{R}^d$.
The main change of perspective when developing models
capable of processing sequences is that we now
focus on inputs that consist of an ordered list
of feature vectors $\mathbf{x}_1, \dots, \mathbf{x}_T$,
where each feature vector $\mathbf{x}_t$ is
indexed by a time step $t \in \mathbb{Z}^+$
lying in $\mathbb{R}^d$.

Some datasets consist of a single massive sequence.
Consider, for example, the extremely long streams
of sensor readings that might be available to climate scientists.
In such cases, we might create training datasets
by randomly sampling subsequences of some predetermined length.
More often, our data arrives as a collection of sequences.
Consider the following examples:
(i) a collection of documents,
each represented as its own sequence of words,
and each having its own length $T_i$;
(ii) sequence representation of
patient stays in the hospital,
where each stay consists of a number of events
and the sequence length depends roughly
on the length of the stay.

Previously, when dealing with individual inputs,
we assumed that they were sampled independently
from the same underlying distribution $P(X)$.
While we still assume that entire sequences
(e.g., entire documents or patient trajectories)
are sampled independently,
we cannot assume that the data arriving
at each time step are independent of each other.
For example, the words that likely to appear later in a document
depend heavily on words occurring earlier in the document.
The medicine a patient is likely to receive
on the 10th day of a hospital visit
depends heavily on what transpired
in the previous nine days.

This should come as no surprise.
If we did not believe that the elements in a sequence were related,
we would not have bothered to model them as a sequence in the first place.
Consider the usefulness of the auto-fill features
that are popular on search tools and modern email clients.
They are useful precisely because it is often possible
to predict (imperfectly, but better than random guessing)
what the likely continuations of a sequence might be,
given some initial prefix.
For most sequence models,
we do not require independence,
or even stationarity, of our sequences.
Instead, we require only that
the sequences themselves are sampled
from some fixed underlying distribution
over entire sequences.

This flexible approach allows for such phenomena
as (i) documents looking significantly different
at the beginning than at the end;
or (ii) patient status evolving either
towards recovery or towards death
over the course of a hospital stay;
or (iii) customer taste evolving in predictable ways
over the course of continued interaction with a recommender system.

We sometimes wish to predict a fixed target $y$
given sequentially structured input
(e.g., sentiment classification based on a movie review).
At other times, we wish to predict a sequentially structured target
($y_1, \ldots, y_T$)
given a fixed input (e.g., image captioning).
Still other times, our goal is to predict sequentially structured targets
based on sequentially structured inputs
(e.g., machine translation or video captioning).
Such sequence-to-sequence tasks take two forms:
(i) *aligned*: where the input at each time step
aligns with a corresponding target (e.g., part of speech tagging);
(ii) *unaligned*: where the input and target
do not necessarily exhibit a step-for-step correspondence
(e.g., machine translation).

Before we worry about handling targets of any kind,
we can tackle the most straightforward problem:
unsupervised density modeling (also called *sequence modeling*).
Here, given a collection of sequences,
our goal is to estimate the probability mass function
that tells us how likely we are to see any given sequence,
i.e., $p(\mathbf{x}_1, \ldots, \mathbf{x}_T)$.

### Autoregressive Models

Before introducing specialized neural networks
designed to handle sequentially structured data,
let's take a look at some actual sequence data
and build up some basic intuitions and statistical tools.
In particular, we will focus on stock price data
from the FTSE 100 index ().
At each *time step* $t \in \mathbb{Z}^+$, we observe
the price, $x_t$, of the index at that time.

Now suppose that a trader would like to make short-term trades,
strategically getting into or out of the index,
depending on whether they believe
that it will rise or decline
in the subsequent time step.
Absent any other features
(news, financial reporting data, etc.),
the only available signal for predicting
the subsequent value is the history of prices to date.
The trader is thus interested in knowing
the probability distribution

would be to apply a linear regression model
(recall ).
Such models that regress the value of a signal
on the previous values of that same signal
are naturally called *autoregressive models*.
There is just one major problem: the number of inputs,
$x_{t-1}, \ldots, x_1$ varies, depending on $t$.
In other words, the number of inputs increases
with the amount of data that we encounter.
Thus if we want to treat our historical data
as a training set, we are left with the problem
that each example has a different number of features.
Much of what follows in this chapter
will revolve around techniques
for overcoming these challenges
when engaging in such *autoregressive* modeling problems
where the object of interest is
$P(x_t \mid x_{t-1}, \ldots, x_1)$
or some statistic(s) of this distribution.

A few strategies recur frequently.
First of all,
we might believe that although long sequences
$x_{t-1}, \ldots, x_1$ are available,
it may not be necessary
to look back so far in the history
when predicting the near future.
In this case we might content ourselves
to condition on some window of length $\tau$
and only use $x_{t-1}, \ldots, x_{t-\tau}$ observations.
The immediate benefit is that now the number of arguments
is always the same, at least for $t > \tau$.
This allows us to train any linear model or deep network
that requires fixed-length vectors as inputs.
Second, we might develop models that maintain
some summary $h_t$ of the past observations
(see )
and at the same time update $h_t$
in addition to the prediction $\hat{x}_t$.
This leads to models that estimate not only $x_t$
with $\hat{x}_t = P(x_t \mid h_{t})$
but also updates of the form
$h_t = g(h_{t-1}, x_{t-1})$.
Since $h_t$ is never observed,
these models are also called
*latent autoregressive models*.

To construct training data from historical data, one
typically creates examples by sampling windows randomly.
In general, we do not expect time to stand still.
However, we often assume that while
the specific values of $x_t$ might change,
the dynamics according to which each subsequent
observation is generated given the previous observations do not.
Statisticians call dynamics that do not change *stationary*.

### Sequence Models

Sometimes, especially when working with language,
we wish to estimate the joint probability
of an entire sequence.
This is a common task when working with sequences
composed of discrete *tokens*, such as words.
Generally, these estimated functions are called *sequence models*
and for natural language data, they are called *language models*.
The field of sequence modeling has been driven so much by natural language processing,
that we often describe sequence models as "language models",
even when dealing with non-language data.
Language models prove useful for all sorts of reasons.
Sometimes we want to evaluate the likelihood of sentences.
For example, we might wish to compare
the naturalness of two candidate outputs
generated by a machine translation system
or by a speech recognition system.
But language modeling gives us not only
the capacity to *evaluate* likelihood,
but the ability to *sample* sequences,
and even to optimize for the most likely sequences.

While language modeling might not, at first glance, look
like an autoregressive problem,
we can reduce language modeling to autoregressive prediction
by decomposing the joint density  of a sequence $p(x_1, \ldots, x_T)$
into the product of conditional densities
in a left-to-right fashion
by applying the chain rule of probability:

We often find it useful to work with models that proceed
as though a Markov condition were satisfied,
even when we know that this is only *approximately* true.
With real text documents we continue to gain information
as we include more and more leftwards context.
But these gains diminish rapidly.
Thus, sometimes we compromise, obviating computational and statistical difficulties
by training models whose validity depends
on a $k^{\textrm{th}}$-order Markov condition.
Even today's massive RNN- and Transformer-based language models
seldom incorporate more than thousands of words of context.

With discrete data, a true Markov model
simply counts the number of times
that each word has occurred in each context, producing
the relative frequency estimate of $P(x_t \mid x_{t-1})$.
Whenever the data assumes only discrete values
(as in language),
the most likely sequence of words can be computed efficiently
using dynamic programming.

#### The Order of Decoding

You may be wondering why we represented
the factorization of a text sequence $P(x_1, \ldots, x_T)$
as a left-to-right chain of conditional probabilities.
Why not right-to-left or some other, seemingly random order?
In principle, there is nothing wrong with unfolding
$P(x_1, \ldots, x_T)$ in reverse order.
The result is a valid factorization:

\hat{x}_{605} &= f(x_{601}, x_{602}, x_{603}, x_{604}), \\
\hat{x}_{606} &= f(x_{602}, x_{603}, x_{604}, \hat{x}_{605}), \\
\hat{x}_{607} &= f(x_{603}, x_{604}, \hat{x}_{605}, \hat{x}_{606}),\\
\hat{x}_{608} &= f(x_{604}, \hat{x}_{605}, \hat{x}_{606}, \hat{x}_{607}),\\
\hat{x}_{609} &= f(\hat{x}_{605}, \hat{x}_{606}, \hat{x}_{607}, \hat{x}_{608}),\\
&\vdots\end{aligned}$$

Generally, for an observed sequence $x_1, \ldots, x_t$,
its predicted output $\hat{x}_{t+k}$ at time step $t+k$
is called the $k$*-step-ahead prediction*.
Since we have observed up to $x_{604}$,
its $k$-step-ahead prediction is $\hat{x}_{604+k}$.
In other words, we will have to
keep on using our own predictions
to make multistep-ahead predictions.
Let's see how well this goes.

Unfortunately, in this case we fail spectacularly.
The predictions decay to a constant
pretty quickly after a few steps.
Why did the algorithm perform so much worse
when predicting further into the future?
Ultimately, this is down to the fact
that errors build up.
Let's say that after step 1 we have some error $\epsilon_1 = \bar\epsilon$.
Now the *input* for step 2 is perturbed by $\epsilon_1$,
hence we suffer some error in the order of
$\epsilon_2 = \bar\epsilon + c \epsilon_1$
for some constant $c$, and so on.
The predictions can diverge rapidly
from the true observations.
You may already be familiar
with this common phenomenon.
For instance, weather forecasts for the next 24 hours
tend to be pretty accurate but beyond that,
accuracy declines rapidly.
We will discuss methods for improving this
throughout this chapter and beyond.

Let's [**take a closer look at the difficulties in $k$-step-ahead predictions**]
by computing predictions on the entire sequence for $k = 1, 4, 16, 64$.

This clearly illustrates how the quality of the prediction changes
as we try to predict further into the future.
While the 4-step-ahead predictions still look good,
anything beyond that is almost useless.

### Summary

There is quite a difference in difficulty
between interpolation and extrapolation.
Consequently, if you have a sequence, always respect
the temporal order of the data when training,
i.e., never train on future data.
Given this kind of data,
sequence models require specialized statistical tools for estimation.
Two popular choices are autoregressive models
and latent-variable autoregressive models.
For causal models (e.g., time going forward),
estimating the forward direction is typically
a lot easier than the reverse direction.
For an observed sequence up to time step $t$,
its predicted output at time step $t+k$
is the $k$*-step-ahead prediction*.
As we predict further in time by increasing $k$,
the errors accumulate and the quality of the prediction degrades,
often dramatically.

### Exercises

1. Improve the model in the experiment of this section.
    1. Incorporate more than the past four observations? How many do you really need?
    1. How many past observations would you need if there was no noise? Hint: you can write $\sin$ and $\cos$ as a differential equation.
    1. Can you incorporate older observations while keeping the total number of features constant? Does this improve accuracy? Why?
    1. Change the neural network architecture and evaluate the performance. You may train the new model with more epochs. What do you observe?
1. An investor wants to find a good security to buy.
   They look at past returns to decide which one is likely to do well.
   What could possibly go wrong with this strategy?
1. Does causality also apply to text? To which extent?
1. Give an example for when a latent autoregressive model
   might be needed to capture the dynamic of the data.

[Discussions](https://discuss.d2l.ai/t/113)

[Discussions](https://discuss.d2l.ai/t/114)

[Discussions](https://discuss.d2l.ai/t/1048)

[Discussions](https://discuss.d2l.ai/t/18010)

## Converting Raw Text into Sequence Data

Throughout this book,
we will often work with text data
represented as sequences
of words, characters, or word pieces.
To get going, we will need some basic
tools for converting raw text
into sequences of the appropriate form.
Typical preprocessing pipelines
execute the following steps:

1. Load text as strings into memory.
1. Split the strings into tokens (e.g., words or characters).
1. Build a vocabulary dictionary to associate each vocabulary element with a numerical index.
1. Convert the text into sequences of numerical indices.

### Reading the Dataset

Here, we will work with H. G. Wells'
[The Time Machine](http://www.gutenberg.org/ebooks/35),
a book containing just over 30,000 words.
While real applications will typically
involve significantly larger datasets,
this is sufficient to demonstrate
the preprocessing pipeline.
The following `_download` method
(**reads the raw text into a string**).

For simplicity, we ignore punctuation and capitalization when preprocessing the raw text.

### Tokenization

*Tokens* are the atomic (indivisible) units of text.
Each time step corresponds to 1 token,
but what precisely constitutes a token is a design choice.
For example, we could represent the sentence
"Baby needs a new pair of shoes"
as a sequence of 7 words,
where the set of all words comprise
a large vocabulary (typically tens
or hundreds of thousands of words).
Or we would represent the same sentence
as a much longer sequence of 30 characters,
using a much smaller vocabulary
(there are only 256 distinct ASCII characters).
Below, we tokenize our preprocessed text
into a sequence of characters.

### Vocabulary

These tokens are still strings.
However, the inputs to our models
must ultimately consist
of numerical inputs.
[**Next, we introduce a class
for constructing *vocabularies*,
i.e., objects that associate
each distinct token value
with a unique index.**]
First, we determine the set of unique tokens in our training *corpus*.
We then assign a numerical index to each unique token.
Rare vocabulary elements are often dropped for convenience.
Whenever we encounter a token at training or test time
that had not been previously seen or was dropped from the vocabulary,
we represent it by a special "&lt;unk&gt;" token,
signifying that this is an *unknown* value.

We now [**construct a vocabulary**] for our dataset,
converting the sequence of strings
into a list of numerical indices.
Note that we have not lost any information
and can easily convert our dataset
back to its original (string) representation.

### Putting It All Together

Using the above classes and methods,
we [**package everything into the following
`build` method of the `TimeMachine` class**],
which returns `corpus`, a list of token indices, and `vocab`,
the vocabulary of *The Time Machine* corpus.
The modifications we did here are:
(i) we tokenize text into characters, not words,
to simplify the training in later sections;
(ii) `corpus` is a single list, not a list of token lists,
since each text line in *The Time Machine* dataset
is not necessarily a sentence or paragraph.

### Exploratory Language Statistics

Using the real corpus and the `Vocab` class defined over words,
we can inspect basic statistics concerning word use in our corpus.
Below, we construct a vocabulary from words used in *The Time Machine*
and print the ten most frequently occurring of them.

Note that (**the ten most frequent words**)
are not all that descriptive.
You might even imagine that
we might see a very similar list
if we had chosen any book at random.
Articles like "the" and "a",
pronouns like "i" and "my",
and prepositions like "of", "to", and "in"
occur often because they serve common syntactic roles.
Such words that are common but not particularly descriptive
are often called (***stop words***) and,
in previous generations of text classifiers
based on so-called bag-of-words representations,
they were most often filtered out.
However, they carry meaning and
it is not necessary to filter them out
when working with modern RNN- and
Transformer-based neural models.
If you look further down the list,
you will notice
that word frequency decays quickly.
The $10^{\textrm{th}}$ most frequent word
is less than $1/5$ as common as the most popular.
Word frequency tends to follow a power law distribution
(specifically the Zipfian) as we go down the ranks.
To get a better idea, we [**plot the figure of the word frequency**].

After dealing with the first few words as exceptions,
all the remaining words roughly follow a straight line on a log--log plot.
This phenomenon is captured by *Zipf's law*,
which states that the frequency $n_i$
of the $i^\textrm{th}$ most frequent word is:

where $\alpha$ is the exponent that characterizes
the distribution and $c$ is a constant.
This should already give us pause for thought if we want
to model words by counting statistics.
After all, we will significantly overestimate the frequency of the tail, also known as the infrequent words. But [**what about the other word combinations, such as two consecutive words (bigrams), three consecutive words (trigrams)**], and beyond?
Let's see whether the bigram frequency behaves in the same manner as the single word (unigram) frequency.

One thing is notable here. Out of the ten most frequent word pairs, nine are composed of both stop words and only one is relevant to the actual book---"the time". Furthermore, let's see whether the trigram frequency behaves in the same manner.

Now, let's [**visualize the token frequency**] among these three models: unigrams, bigrams, and trigrams.

This figure is quite exciting.
First, beyond unigram words, sequences of words
also appear to be following Zipf's law,
albeit with a smaller exponent
$\alpha$ in ,
depending on the sequence length.
Second, the number of distinct $n$-grams is not that large.
This gives us hope that there is quite a lot of structure in language.
Third, many $n$-grams occur very rarely.
This makes certain methods unsuitable for language modeling
and motivates the use of deep learning models.
We will discuss this in the next section.

### Summary

Text is among the most common forms of sequence data encountered in deep learning.
Common choices for what constitutes a token are characters, words, and word pieces.
To preprocess text, we usually (i) split text into tokens; (ii) build a vocabulary to map token strings to numerical indices; and (iii) convert text data into token indices for models to manipulate.
In practice, the frequency of words tends to follow Zipf's law. This is true not just for individual words (unigrams), but also for $n$-grams.

### Exercises

1. In the experiment of this section, tokenize text into words and vary the `min_freq` argument value of the `Vocab` instance. Qualitatively characterize how changes in `min_freq` impact the size of the resulting vocabulary.
1. Estimate the exponent of Zipfian distribution for unigrams, bigrams, and trigrams in this corpus.
1. Find some other sources of data (download a standard machine learning dataset, pick another public domain book,
   scrape a website, etc). For each, tokenize the data at both the word and character levels. How do the vocabulary sizes compare with *The Time Machine* corpus at equivalent values of `min_freq`. Estimate the exponent of the Zipfian distribution corresponding to the unigram and bigram distributions for these corpora. How do they compare with the values that you observed for *The Time Machine* corpus?

[Discussions](https://discuss.d2l.ai/t/117)

[Discussions](https://discuss.d2l.ai/t/118)

[Discussions](https://discuss.d2l.ai/t/1049)

[Discussions](https://discuss.d2l.ai/t/18011)

## Language Models

In , we saw how to map text sequences into tokens, where these tokens can be viewed as a sequence of discrete observations such as words or characters. Assume that the tokens in a text sequence of length $T$ are in turn $x_1, x_2, \ldots, x_T$.
The goal of *language models*
is to estimate the joint probability of the whole sequence:

For example,
the probability of a text sequence containing four words would be given as:

\begin{aligned}
P(x_1, x_2, x_3, x_4) &=  P(x_1) P(x_2) P(x_3) P(x_4),\\
P(x_1, x_2, x_3, x_4) &=  P(x_1) P(x_2  \mid  x_1) P(x_3  \mid  x_2) P(x_4  \mid  x_3),\\
P(x_1, x_2, x_3, x_4) &=  P(x_1) P(x_2  \mid  x_1) P(x_3  \mid  x_1, x_2) P(x_4  \mid  x_2, x_3).
\end{aligned}

where $n(x)$ and $n(x, x')$ are the number of occurrences of singletons
and consecutive word pairs, respectively.
Unfortunately,
estimating the
probability of a word pair is somewhat more difficult, since the
occurrences of "deep learning" are a lot less frequent.
In particular, for some unusual word combinations it may be tricky to
find enough occurrences to get accurate estimates.
As suggested by the empirical results in ,
things take a turn for the worse for three-word combinations and beyond.
There will be many plausible three-word combinations that we likely will not see in our dataset.
Unless we provide some solution to assign such word combinations a nonzero count, we will not be able to use them in a language model. If the dataset is small or if the words are very rare, we might not find even a single one of them.

#### Laplace Smoothing

A common strategy is to perform some form of *Laplace smoothing*.
The solution is to
add a small constant to all counts.
Denote by $n$ the total number of words in
the training set
and $m$ the number of unique words.
This solution helps with singletons, e.g., via

where $P$ is given by a language model and $x_t$ is the actual token observed at time step $t$ from the sequence.
This makes the performance on documents of different lengths comparable. For historical reasons, scientists in natural language processing prefer to use a quantity called *perplexity*. In a nutshell, it is the exponential of :

## Recurrent Neural Networks

In  we described Markov models and $n$-grams for language modeling, where the conditional probability of token $x_t$ at time step $t$ only depends on the $n-1$ previous tokens.
If we want to incorporate the possible effect of tokens earlier than time step $t-(n-1)$ on $x_t$,
we need to increase $n$.
However, the number of model parameters would also increase exponentially with it, as we need to store $|\mathcal{V}|^n$ numbers for a vocabulary set $\mathcal{V}$.
Hence, rather than modeling $P(x_t \mid x_{t-1}, \ldots, x_{t-n+1})$ it is preferable to use a latent variable model,

For a sufficiently powerful function $f$ in , the latent variable model is not an approximation. After all, $h_t$ may simply store all the data it has observed so far.
However, it could potentially make both computation and storage expensive.

Recall that we have discussed hidden layers with hidden units in .
It is noteworthy that
hidden layers and hidden states refer to two very different concepts.
Hidden layers are, as explained, layers that are hidden from view on the path from input to output.
Hidden states are technically speaking *inputs* to whatever we do at a given step,
and they can only be computed by looking at data at previous time steps.

*Recurrent neural networks* (RNNs) are neural networks with hidden states. Before introducing the RNN model, we first revisit the MLP model introduced in .

### Neural Networks without Hidden States

Let's take a look at an MLP with a single hidden layer.
Let the hidden layer's activation function be $\phi$.
Given a minibatch of examples $\mathbf{X} \in \mathbb{R}^{n \times d}$ with batch size $n$ and $d$ inputs, the hidden layer output $\mathbf{H} \in \mathbb{R}^{n \times h}$ is calculated as

where $\mathbf{O} \in \mathbb{R}^{n \times q}$ is the output variable, $\mathbf{W}_{\textrm{hq}} \in \mathbb{R}^{h \times q}$ is the weight parameter, and $\mathbf{b}_\textrm{q} \in \mathbb{R}^{1 \times q}$ is the bias parameter of the output layer.  If it is a classification problem, we can use $\mathrm{softmax}(\mathbf{O})$ to compute the probability distribution of the output categories.

This is entirely analogous to the regression problem we solved previously in , hence we omit details.
Suffice it to say that we can pick feature-label pairs at random and learn the parameters of our network via automatic differentiation and stochastic gradient descent.

### Recurrent Neural Networks with Hidden States

Matters are entirely different when we have hidden states. Let's look at the structure in some more detail.

Assume that we have
a minibatch of inputs
$\mathbf{X}_t \in \mathbb{R}^{n \times d}$
at time step $t$.
In other words,
for a minibatch of $n$ sequence examples,
each row of $\mathbf{X}_t$ corresponds to one example at time step $t$ from the sequence.
Next,
denote by $\mathbf{H}_t  \in \mathbb{R}^{n \times h}$ the hidden layer output of time step $t$.
Unlike with MLP, here we save the hidden layer output $\mathbf{H}_{t-1}$ from the previous time step and introduce a new weight parameter $\mathbf{W}_{\textrm{hh}} \in \mathbb{R}^{h \times h}$ to describe how to use the hidden layer output of the previous time step in the current time step. Specifically, the calculation of the hidden layer output of the current time step is determined by the input of the current time step together with the hidden layer output of the previous time step:

Parameters of the RNN
include the weights $\mathbf{W}_{\textrm{xh}} \in \mathbb{R}^{d \times h}, \mathbf{W}_{\textrm{hh}} \in \mathbb{R}^{h \times h}$,
and the bias $\mathbf{b}_\textrm{h} \in \mathbb{R}^{1 \times h}$
of the hidden layer,
together with the weights $\mathbf{W}_{\textrm{hq}} \in \mathbb{R}^{h \times q}$
and the bias $\mathbf{b}_\textrm{q} \in \mathbb{R}^{1 \times q}$
of the output layer.
It is worth mentioning that
even at different time steps,
RNNs always use these model parameters.
Therefore, the parametrization cost of an RNN
does not grow as the number of time steps increases.

At any time step $t$,
the computation of the hidden state can be treated as:
(i) concatenating the input $\mathbf{X}_t$ at the current time step $t$ and the hidden state $\mathbf{H}_{t-1}$ at the previous time step $t-1$;
(ii) feeding the concatenation result into a fully connected layer with the activation function $\phi$.
The output of such a fully connected layer is the hidden state $\mathbf{H}_t$ of the current time step $t$.
In this case,
the model parameters are the concatenation of $\mathbf{W}_{\textrm{xh}}$ and $\mathbf{W}_{\textrm{hh}}$, and a bias of $\mathbf{b}_\textrm{h}$, all from .
The hidden state of the current time step $t$, $\mathbf{H}_t$, will participate in computing the hidden state $\mathbf{H}_{t+1}$ of the next time step $t+1$.
What is more, $\mathbf{H}_t$ will also be
fed into the fully connected output layer
to compute the output
$\mathbf{O}_t$ of the current time step $t$.

We just mentioned that the calculation of $\mathbf{X}_t \mathbf{W}_{\textrm{xh}} + \mathbf{H}_{t-1} \mathbf{W}_{\textrm{hh}}$ for the hidden state is equivalent to
matrix multiplication of the
concatenation of $\mathbf{X}_t$ and $\mathbf{H}_{t-1}$
and the
concatenation of $\mathbf{W}_{\textrm{xh}}$ and $\mathbf{W}_{\textrm{hh}}$.
Though this can be proven mathematically,
in the following we just use a simple code snippet as a demonstration.
To begin with,
we define matrices `X`, `W_xh`, `H`, and `W_hh`, whose shapes are (3, 1), (1, 4), (3, 4), and (4, 4), respectively.
Multiplying `X` by `W_xh`, and `H` by `W_hh`, and then adding these two products,
we obtain a matrix of shape (3, 4).

Now we concatenate the matrices `X` and `H`
along columns (axis 1),
and the matrices
`W_xh` and `W_hh` along rows (axis 0).
These two concatenations
result in
matrices of shape (3, 5)
and of shape (5, 4), respectively.
Multiplying these two concatenated matrices,
we obtain the same output matrix of shape (3, 4)
as above.

### RNN-Based Character-Level Language Models

Recall that for language modeling in ,
we aim to predict the next token based on
the current and past tokens;
thus we shift the original sequence by one token
as the targets (labels).
to use a neural network for language modeling.
In the following we illustrate how RNNs can be used to build a language model.
Let the minibatch size be one, and the sequence of the text be "machine".
To simplify training in subsequent sections,
we tokenize text into characters rather than words
and consider a *character-level language model*.

During the training process,
we run a softmax operation on the output from the output layer for each time step, and then use the cross-entropy loss to compute the error between the model output and the target.
Because of the recurrent computation of the hidden state in the hidden layer, the output, $\mathbf{O}_3$,  of time step 3 in  is determined by the text sequence "m", "a", and "c". Since the next character of the sequence in the training data is "h", the loss of time step 3 will depend on the probability distribution of the next character generated based on the feature sequence "m", "a", "c" and the target "h" of this time step.

In practice, each token is represented by a $d$-dimensional vector, and we use a batch size $n>1$. Therefore, the input $\mathbf X_t$ at time step $t$ will be an $n\times d$ matrix, which is identical to what we discussed in .

In the following sections, we will implement RNNs
for character-level language models.

### Summary

A neural network that uses recurrent computation for hidden states is called a recurrent neural network (RNN).
The hidden state of an RNN can capture historical information of the sequence up to the current time step. With recurrent computation, the number of RNN model parameters does not grow as the number of time steps increases. As for applications, an RNN can be used to create character-level language models.

### Exercises

1. If we use an RNN to predict the next character in a text sequence, what is the required dimension for any output?
1. Why can RNNs express the conditional probability of a token at some time step based on all the previous tokens in the text sequence?
1. What happens to the gradient if you backpropagate through a long sequence?
1. What are some of the problems associated with the language model described in this section?

[Discussions](https://discuss.d2l.ai/t/337)

[Discussions](https://discuss.d2l.ai/t/1050)

[Discussions](https://discuss.d2l.ai/t/1051)

[Discussions](https://discuss.d2l.ai/t/180013)

## Backpropagation Through Time

If you completed the exercises in ,
you would have seen that gradient clipping is vital
for preventing the occasional massive gradients
from destabilizing training.
We hinted that the exploding gradients
stem from backpropagating across long sequences.
Before introducing a slew of modern RNN architectures,
let's take a closer look at how *backpropagation*
works in sequence models in mathematical detail.
Hopefully, this discussion will bring some precision
to the notion of *vanishing* and *exploding* gradients.
If you recall our discussion of forward and backward
propagation through computational graphs
when we introduced MLPs in ,
then forward propagation in RNNs
should be relatively straightforward.
Applying backpropagation in RNNs
is called *backpropagation through time* .
This procedure requires us to expand (or unroll)
the computational graph of an RNN
one time step at a time.
The unrolled RNN is essentially
a feedforward neural network
with the special property
that the same parameters
are repeated throughout the unrolled network,
appearing at each time step.
Then, just as in any feedforward neural network,
we can apply the chain rule,
backpropagating gradients through the unrolled net.
The gradient with respect to each parameter
must be summed across all places
that the parameter occurs in the unrolled net.
Handling such weight tying should be familiar
from our chapters on convolutional neural networks.

Complications arise because sequences
can be rather long.
It is not unusual to work with text sequences
consisting of over a thousand tokens.
Note that this poses problems both from
a computational (too much memory)
and optimization (numerical instability)
standpoint.
Input from the first step passes through
over 1000 matrix products before arriving at the output,
and another 1000 matrix products
are required to compute the gradient.
We now analyze what can go wrong and
how to address it in practice.

### Analysis of Gradients in RNNs

We start with a simplified model of how an RNN works.
This model ignores details about the specifics
of the hidden state and how it is updated.
The mathematical notation here
does not explicitly distinguish
scalars, vectors, and matrices.
We are just trying to develop some intuition.
In this simplified model,
we denote $h_t$ as the hidden state,
$x_t$ as input, and $o_t$ as output
at time step $t$.
Recall our discussions in
that the input and the hidden state
can be concatenated before being multiplied
by one weight variable in the hidden layer.
Thus, we use $w_\textrm{h}$ and $w_\textrm{o}$ to indicate the weights
of the hidden layer and the output layer, respectively.
As a result, the hidden states and outputs
at each time step are

For backpropagation, matters are a bit trickier,
especially when we compute the gradients
with regard to the parameters $w_\textrm{h}$ of the objective function $L$.
To be specific, by the chain rule,

To derive the above gradient, assume that we have
three sequences $\{a_{t}\},\{b_{t}\},\{c_{t}\}$
satisfying $a_{0}=0$ and $a_{t}=b_{t}+c_{t}a_{t-1}$ for $t=1, 2,\ldots$.
Then for $t\geq 1$, it is easy to show

b_t &= \frac{\partial f(x_{t},h_{t-1},w_\textrm{h})}{\partial w_\textrm{h}}, \\
c_t &= \frac{\partial f(x_{t},h_{t-1},w_\textrm{h})}{\partial h_{t-1}},\end{aligned}$$

the gradient computation in  satisfies
$a_{t}=b_{t}+c_{t}a_{t-1}$.
Thus, per ,
we can remove the recurrent computation
in  with

It follows from the definition of $\xi_t$
that $E[z_t] = \partial h_t/\partial w_\textrm{h}$.
Whenever $\xi_t = 0$ the recurrent computation
terminates at that time step $t$.
This leads to a weighted sum of sequences of varying lengths,
where long sequences are rare but appropriately overweighted.
This idea was proposed by

#### Comparing Strategies

when analyzing the first few characters of *The Time Machine*
using backpropagation through time for RNNs:

* The first row is the randomized truncation that partitions the text into segments of varying lengths.
* The second row is the regular truncation that breaks the text into subsequences of the same length. This is what we have been doing in RNN experiments.
* The third row is the full backpropagation through time that leads to a computationally infeasible expression.

Unfortunately, while appealing in theory,
randomized truncation does not work
much better than regular truncation,
most likely due to a number of factors.
First, the effect of an observation
after a number of backpropagation steps
into the past is quite sufficient
to capture dependencies in practice.
Second, the increased variance counteracts the fact
that the gradient is more accurate with more steps.
Third, we actually *want* models that have only
a short range of interactions.
Hence, regularly truncated backpropagation through time
has a slight regularizing effect that can be desirable.

### Backpropagation Through Time in Detail

After discussing the general principle,
let's discuss backpropagation through time in detail.
In contrast to the analysis in ,
in the following we will show how to compute
the gradients of the objective function
with respect to all the decomposed model parameters.
To keep things simple, we consider
an RNN without bias parameters,
whose activation function in the hidden layer
uses the identity mapping ($\phi(x)=x$).
For time step $t$, let the single example input
and the target be $\mathbf{x}_t \in \mathbb{R}^d$ and $y_t$, respectively.
The hidden state $\mathbf{h}_t \in \mathbb{R}^h$
and the output $\mathbf{o}_t \in \mathbb{R}^q$
are computed as

In order to visualize the dependencies among
model variables and parameters during computation
of the RNN,
we can draw a computational graph for the model,
as shown in .
For example, the computation of the hidden states of time step 3,
$\mathbf{h}_3$, depends on the model parameters
$\mathbf{W}_\textrm{hx}$ and $\mathbf{W}_\textrm{hh}$,
the hidden state of the previous time step $\mathbf{h}_2$,
and the input of the current time step $\mathbf{x}_3$.

As just mentioned, the model parameters in
are $\mathbf{W}_\textrm{hx}$, $\mathbf{W}_\textrm{hh}$, and $\mathbf{W}_\textrm{qh}$.
Generally, training this model requires
gradient computation with respect to these parameters
$\partial L/\partial \mathbf{W}_\textrm{hx}$, $\partial L/\partial \mathbf{W}_\textrm{hh}$, and $\partial L/\partial \mathbf{W}_\textrm{qh}$.
According to the dependencies in ,
we can traverse in the opposite direction of the arrows
to calculate and store the gradients in turn.
To flexibly express the multiplication of
matrices, vectors, and scalars of different shapes
in the chain rule,
we continue to use the $\textrm{prod}$ operator
as described in .

First of all, differentiating the objective function
with respect to the model output at any time step $t$
is fairly straightforward:

\frac{\partial L}{\partial \mathbf{W}_\textrm{qh}}
= \sum_{t=1}^T \textrm{prod}\left(\frac{\partial L}{\partial \mathbf{o}_t}, \frac{\partial \mathbf{o}_t}{\partial \mathbf{W}_\textrm{qh}}\right)
= \sum_{t=1}^T \frac{\partial L}{\partial \mathbf{o}_t} \mathbf{h}_t^\top,

It gets trickier for any time step $t < T$,
where the objective function $L$ depends on
$\mathbf{h}_t$ via $\mathbf{h}_{t+1}$ and $\mathbf{o}_t$.
According to the chain rule,
the gradient of the hidden state
$\partial L/\partial \mathbf{h}_t \in \mathbb{R}^h$
at any time step $t < T$ can be recurrently computed as:

We can see from
that this simple linear example already
exhibits some key problems of long sequence models:
it involves potentially very large powers of $\mathbf{W}_\textrm{hh}^\top$.
In it, eigenvalues smaller than 1 vanish
and eigenvalues larger than 1 diverge.
This is numerically unstable,
which manifests itself in the form of vanishing
and exploding gradients.
One way to address this is to truncate the time steps
at a computationally convenient size
as discussed in .
In practice, this truncation can also be effected
by detaching the gradient after a given number of time steps.
Later on, we will see how more sophisticated sequence models
such as long short-term memory can alleviate this further.

Finally,  shows
that the objective function $L$
depends on model parameters $\mathbf{W}_\textrm{hx}$ and $\mathbf{W}_\textrm{hh}$
in the hidden layer via hidden states
$\mathbf{h}_1, \ldots, \mathbf{h}_T$.
To compute gradients with respect to such parameters
$\partial L / \partial \mathbf{W}_\textrm{hx} \in \mathbb{R}^{h \times d}$ and $\partial L / \partial \mathbf{W}_\textrm{hh} \in \mathbb{R}^{h \times h}$,
we apply the chain rule giving

where $\partial L/\partial \mathbf{h}_t$
which is recurrently computed by
and
is the key quantity that affects the numerical stability.

Since backpropagation through time is the application of backpropagation in RNNs,
as we have explained in ,
training RNNs alternates forward propagation with
backpropagation through time.
Moreover, backpropagation through time
computes and stores the above gradients in turn.
Specifically, stored intermediate values
are reused to avoid duplicate calculations,
such as storing $\partial L/\partial \mathbf{h}_t$
to be used in computation of both $\partial L / \partial \mathbf{W}_\textrm{hx}$
and $\partial L / \partial \mathbf{W}_\textrm{hh}$.

### Summary

Backpropagation through time is merely an application of backpropagation to sequence models with a hidden state.
Truncation, such as regular or randomized, is needed for computational convenience and numerical stability.
High powers of matrices can lead to divergent or vanishing eigenvalues. This manifests itself in the form of exploding or vanishing gradients.
For efficient computation, intermediate values are cached during backpropagation through time.

### Exercises

1. Assume that we have a symmetric matrix $\mathbf{M} \in \mathbb{R}^{n \times n}$ with eigenvalues $\lambda_i$ whose corresponding eigenvectors are $\mathbf{v}_i$ ($i = 1, \ldots, n$). Without loss of generality, assume that they are ordered in the order $|\lambda_i| \geq |\lambda_{i+1}|$.
   1. Show that $\mathbf{M}^k$ has eigenvalues $\lambda_i^k$.
   1. Prove that for a random vector $\mathbf{x} \in \mathbb{R}^n$, with high probability $\mathbf{M}^k \mathbf{x}$ will be very much aligned with the eigenvector $\mathbf{v}_1$
of $\mathbf{M}$. Formalize this statement.
   1. What does the above result mean for gradients in RNNs?
1. Besides gradient clipping, can you think of any other methods to cope with gradient explosion in recurrent neural networks?

[Discussions](https://discuss.d2l.ai/t/334)

# Attention Mechanisms and Transformers

The earliest years of the deep learning boom were driven primarily
by results produced using the multilayer perceptron,
convolutional network, and recurrent network architectures.
Remarkably, the model architectures that underpinned
many of deep learning's breakthroughs in the 2010s
had changed remarkably little relative to their
antecedents despite the lapse of nearly 30 years.
While plenty of new methodological innovations
made their way into most practitioner's toolkits---ReLU
activations, residual layers, batch normalization, dropout,
and adaptive learning rate schedules come to mind---the core
underlying architectures were clearly recognizable as
scaled-up implementations of classic ideas.
Despite thousands of papers proposing alternative ideas,
models resembling classical convolutional neural networks ()
retained *state-of-the-art* status in computer vision
and models resembling Sepp Hochreiter's original design
for the LSTM recurrent neural network (),
dominated most applications in natural language processing.
Arguably, to that point, the rapid emergence of deep learning
appeared to be primarily attributable to shifts
in the available computational resources
(thanks to innovations in parallel computing with GPUs)
and the availability of massive data resources
(thanks to cheap storage and Internet services).
While these factors may indeed remain the primary drivers
behind this technology's increasing power
we are also witnessing, at long last,
a sea change in the landscape of dominant architectures.

At the present moment, the dominant models
for nearly all natural language processing tasks
are based on the Transformer architecture.
Given any new task in natural language processing, the default first-pass approach
is to grab a large Transformer-based pretrained model,
(e.g., BERT , ELECTRA , RoBERTa , or Longformer )
adapting the output layers as necessary,
and fine-tuning the model on the available
data for the downstream task.
If you have been paying attention to the last few years
of breathless news coverage centered on OpenAI's
large language models, then you have been tracking a conversation
centered on the GPT-2 and GPT-3 Transformer-based models .
Meanwhile, the vision Transformer has emerged
as a default model for diverse vision tasks,
including image recognition, object detection,
semantic segmentation, and superresolution .
Transformers also showed up as competitive methods
for speech recognition ,
reinforcement learning ,
and graph neural networks .

The core idea behind the Transformer model is the *attention mechanism*,
an innovation that was originally envisioned as an enhancement
for encoder--decoder RNNs applied to sequence-to-sequence applications,
such as machine translations .
You might recall that in the first sequence-to-sequence models
for machine translation ,
the entire input was compressed by the encoder
into a single fixed-length vector to be fed into the decoder.
The intuition behind attention is that rather than compressing the input,
it might be better for the decoder to revisit the input sequence at every step.
Moreover, rather than always seeing the same representation of the input,
one might imagine that the decoder should selectively focus
on particular parts of the input sequence at particular decoding steps.
Bahdanau's attention mechanism provided a simple means
by which the decoder could dynamically *attend* to different
parts of the input at each decoding step.
The high-level idea is that the encoder could produce a representation
of length equal to the original input sequence.
Then, at decoding time, the decoder can (via some control mechanism)
receive as input a context vector consisting of a weighted sum
of the representations on the input at each time step.
Intuitively, the weights determine the extent
to which each step's context "focuses" on each input token,
and the key is to make this process
for assigning the weights differentiable
so that it can be learned along with
all of the other neural network parameters.

Initially, the idea was a remarkably successful
enhancement to the recurrent neural networks
that already dominated machine translation applications.
The models performed better than the original
encoder--decoder sequence-to-sequence architectures.
Furthermore, researchers noted that some nice qualitative insights
sometimes emerged from inspecting the pattern of attention weights.
In translation tasks, attention models
often assigned high attention weights to cross-lingual synonyms
when generating the corresponding words in the target language.
For example, when translating the sentence "my feet hurt"
to "j'ai mal au pieds", the neural network might assign
high attention weights to the representation of "feet"
when generating the corresponding French word "pieds".
These insights spurred claims that attention models confer "interpretability"
although what precisely the attention weights mean---i.e.,
how, if at all, they should be *interpreted* remains a hazy research topic.

However, attention mechanisms soon emerged as more significant concerns,
beyond their usefulness as an enhancement for encoder--decoder recurrent neural networks
and their putative usefulness for picking out salient inputs.
the Transformer architecture for machine translation,
dispensing with recurrent connections altogether,
and instead relying on cleverly arranged attention mechanisms
to capture all relationships among input and output tokens.
The architecture performed remarkably well,
and by 2018 the Transformer began showing up
in the majority of state-of-the-art natural language processing systems.
Moreover, at the same time, the dominant practice in natural language processing
became to pretrain large-scale models
on enormous generic background corpora
to optimize some self-supervised pretraining objective,
and then to fine-tune these models
using the available downstream data.
The gap between Transformers and traditional architectures
grew especially wide when applied in this pretraining paradigm,
and thus the ascendance of Transformers coincided
with the ascendence of such large-scale pretrained models,
now sometimes called *foundation models* .

In this chapter, we introduce attention models,
starting with the most basic intuitions
and the simplest instantiations of the idea.
We then work our way up to the Transformer architecture,
the vision Transformer, and the landscape
of modern Transformer-based pretrained models.

## Queries, Keys, and Values

So far all the networks we have reviewed crucially relied on the input being of a well-defined size. For instance, the images in ImageNet are of size $224 \times 224$ pixels and CNNs are specifically tuned to this size. Even in natural language processing the input size for RNNs is well defined and fixed. Variable size is addressed by sequentially processing one token at a time, or by specially designed convolution kernels . This approach can lead to significant problems when the input is truly of varying size with varying information content, such as in  in the transformation of text . In particular, for long sequences it becomes quite difficult to keep track of everything that has already been generated or even viewed by the network. Even explicit tracking heuristics such as proposed by  only offer limited benefit.

Compare this to databases. In their simplest form they are collections of keys ($k$) and values ($v$). For instance, our database $\mathcal{D}$ might consist of tuples \{("Zhang", "Aston"), ("Lipton", "Zachary"), ("Li", "Mu"), ("Smola", "Alex"), ("Hu", "Rachel"), ("Werness", "Brent")\} with the last name being the key and the first name being the value. We can operate on $\mathcal{D}$, for instance with the exact query ($q$) for "Li" which would return the value "Mu". If ("Li", "Mu") was not a record in $\mathcal{D}$, there would be no valid answer. If we also allowed for approximate matches, we would retrieve ("Lipton", "Zachary") instead. This quite simple and trivial example nonetheless teaches us a number of useful things:

* We can design queries $q$ that operate on ($k$,$v$) pairs in such a manner as to be valid regardless of the  database size.
* The same query can receive different answers, according to the contents of the database.
* The "code" being executed for operating on a large state space (the database) can be quite simple (e.g., exact match, approximate match, top-$k$).
* There is no need to compress or simplify the database to make the operations effective.

Clearly we would not have introduced a simple database here if it wasn't for the purpose of explaining deep learning. Indeed, this leads to one of the most exciting concepts introduced in deep learning in the past decade: the *attention mechanism* . We will cover the specifics of its application to machine translation later. For now, simply consider the following: denote by $\mathcal{D} \stackrel{\textrm{def}}{=} \{(\mathbf{k}_1, \mathbf{v}_1), \ldots (\mathbf{k}_m, \mathbf{v}_m)\}$ a database of $m$ tuples of *keys* and *values*. Moreover, denote by $\mathbf{q}$ a *query*. Then we can define the *attention* over $\mathcal{D}$ as

In particular, to ensure that the weights are also nonnegative, one can resort to exponentiation. This means that we can now pick *any* function  $a(\mathbf{q}, \mathbf{k})$ and then apply the softmax operation used for multinomial models to it via

## Attention Pooling by Similarity

Now that we have introduced the primary components of the attention mechanism, let's use them in a rather classical setting, namely regression and classification via kernel density estimation . This detour simply provides additional background: it is entirely optional and can be skipped if needed.
At their core, Nadaraya--Watson estimators rely on some similarity kernel $\alpha(\mathbf{q}, \mathbf{k})$ relating queries $\mathbf{q}$ to keys $\mathbf{k}$. Some common kernels are

There are many more choices that we could pick. See a [Wikipedia article](https://en.wikipedia.org/wiki/Kernel_(statistics)) for a more extensive review and how the choice of kernels is related to kernel density estimation, sometimes also called *Parzen Windows* . All of the kernels are heuristic and can be tuned. For instance, we can adjust the width, not only on a global basis but even on a per-coordinate basis. Regardless, all of them lead to the following equation for regression and classification alike:

where $\epsilon$ is drawn from a normal distribution with zero mean and unit variance. We draw 40 training examples.

### [**Attention Pooling via Nadaraya--Watson Regression**]

Now that we have data and kernels, all we need is a function that computes the kernel regression estimates. Note that we also want to obtain the relative kernel weights in order to perform some minor diagnostics. Hence we first compute the kernel between all training features (covariates) `x_train` and all validation features `x_val`. This yields a matrix, which we subsequently normalize. When multiplied with the training labels `y_train` we obtain the estimates.

Recall attention pooling in . Let each validation feature be a query, and each training feature--label pair be a key--value pair. As a result, the  normalized relative kernel weights (`attention_w` below) are the *attention weights*.

Let's have a look at the kind of estimates that the different kernels produce.

The first thing that stands out is that all three nontrivial kernels (Gaussian, Boxcar, and Epanechikov) produce fairly workable estimates that are not too far from the true function. Only the constant kernel that leads to the trivial estimate $f(x) = \frac{1}{n} \sum_i y_i$ produces a rather unrealistic result. Let's inspect the attention weighting a bit more closely:

The visualization clearly shows why the estimates for Gaussian, Boxcar, and Epanechikov are very similar: after all, they are derived from very similar attention weights, despite the different functional form of the kernel. This raises the question as to whether this is always the case.

### [**Adapting Attention Pooling**]

We could replace the Gaussian kernel with one of a different width. That is, we could use
$\alpha(\mathbf{q}, \mathbf{k}) = \exp\left(-\frac{1}{2 \sigma^2} \|\mathbf{q} - \mathbf{k}\|^2 \right)$ where $\sigma^2$ determines the width of the kernel. Let's see whether this affects the outcomes.

Clearly, the narrower the kernel, the less smooth the estimate. At the same time, it adapts better to the local variations. Let's look at the corresponding attention weights.

As we would expect, the narrower the kernel, the narrower the range of large attention weights. It is also clear that picking the same width might not be ideal. In fact,  proposed a heuristic that depends on the local density. Many more such "tricks" have been proposed. For instance,  used a similar nearest-neighbor interpolation technique for designing cross-modal image and text representations.

The astute reader might wonder why we are providing this deep dive for a method that is over half a century old. First, it is one of the earliest precursors of modern attention mechanisms. Second, it is great for visualization. Third, and just as importantly, it demonstrates the limits of hand-crafted attention mechanisms. A much better strategy is to *learn* the mechanism, by learning the representations for queries and keys. This is what we will embark on in the following sections.

### Summary

Nadaraya--Watson kernel regression is an early precursor of the current attention mechanisms.
It can be used directly with little to no training or tuning, either for classification or regression.
The attention weight is assigned according to the similarity (or distance) between query and key, and according to how many similar observations are available.

### Exercises

1. Parzen windows density estimates are given by $\hat{p}(\mathbf{x}) = \frac{1}{n} \sum_i k(\mathbf{x}, \mathbf{x}_i)$. Prove that for binary classification the function $\hat{p}(\mathbf{x}, y=1) - \hat{p}(\mathbf{x}, y=-1)$, as obtained by Parzen windows is equivalent to Nadaraya--Watson classification.
1. Implement stochastic gradient descent to learn a good value for kernel widths in Nadaraya--Watson regression.
    1. What happens if you just use the above estimates to minimize $(f(\mathbf{x_i}) - y_i)^2$ directly? Hint: $y_i$ is part of the terms used to compute $f$.
    1. Remove $(\mathbf{x}_i, y_i)$ from the estimate for $f(\mathbf{x}_i)$ and optimize over the kernel widths. Do you still observe overfitting?
1. Assume that all $\mathbf{x}$ lie on the unit sphere, i.e., all satisfy $\|\mathbf{x}\| = 1$. Can you simplify the $\|\mathbf{x} - \mathbf{x}_i\|^2$ term in the exponential? Hint: we will later see that this is very closely related to dot product attention.
1. Recall that  proved that Nadaraya--Watson estimation is consistent. How quickly should you reduce the scale for the attention mechanism as you get more data? Provide some intuition for your answer. Does it depend on the dimensionality of the data? How?

[Discussions](https://discuss.d2l.ai/t/1598)

[Discussions](https://discuss.d2l.ai/t/1599)

[Discussions](https://discuss.d2l.ai/t/3866)

[Discussions](https://discuss.d2l.ai/t/18026)

## Attention Scoring Functions

In ,
we used a number of different distance-based kernels, including a Gaussian kernel to model
interactions between queries and keys. As it turns out, distance functions are slightly more expensive to compute than dot products. As such,
with the softmax operation to ensure nonnegative attention weights,
much of the work has gone into *attention scoring functions* $a$ in  and  that are simpler to compute.

### [**Dot Product Attention**]

Let's review the attention function (without exponentiation) from the Gaussian kernel for a moment:

First, note that the final term depends on $\mathbf{q}$ only. As such it is identical for all $(\mathbf{q}, \mathbf{k}_i)$ pairs. Normalizing the attention weights to $1$, as is done in , ensures that this term disappears entirely. Second, note that both batch and layer normalization (to be discussed later) lead to activations that have well-bounded, and often constant, norms $\|\mathbf{k}_i\|$. This is the case, for instance, whenever the keys $\mathbf{k}_i$ were generated by a layer norm. As such, we can drop it from the definition of $a$ without any major change in the outcome.

Last, we need to keep the order of magnitude of the arguments in the exponential function under control. Assume that all the elements of the query $\mathbf{q} \in \mathbb{R}^d$ and the key $\mathbf{k}_i \in \mathbb{R}^d$ are independent and identically drawn random variables with zero mean and unit variance. The dot product between both vectors has zero mean and a variance of $d$. To ensure that the variance of the dot product still remains $1$ regardless of vector length, we use the *scaled dot product attention* scoring function. That is, we rescale the dot product by $1/\sqrt{d}$. We thus arrive at the first commonly used attention function that is used, e.g., in Transformers :

As it turns out, all popular attention mechanisms use the softmax, hence we will limit ourselves to that in the remainder of this chapter.

### Convenience Functions

We need a few functions to make the attention mechanism efficient to deploy. This includes tools for dealing with strings of variable lengths (common for natural language processing) and tools for efficient evaluation on minibatches (batch matrix multiplication).

#### [**Masked Softmax Operation**]

One of the most popular applications of the attention mechanism is to sequence models. Hence we need to be able to deal with sequences of different lengths. In some cases, such sequences may end up in the same minibatch, necessitating padding with dummy tokens for shorter sequences (see  for an example). These special tokens do not carry meaning. For instance, assume that we have the following three sentences:

Since we do not want blanks in our attention model we simply need to limit $\sum_{i=1}^n \alpha(\mathbf{q}, \mathbf{k}_i) \mathbf{v}_i$ to $\sum_{i=1}^l \alpha(\mathbf{q}, \mathbf{k}_i) \mathbf{v}_i$ for however long, $l \leq n$, the actual sentence is. Since it is such a common problem, it has a name: the *masked softmax operation*.

Let's implement it. Actually, the implementation cheats ever so slightly by setting the values of $\mathbf{v}_i$, for $i > l$, to zero. Moreover, it sets the attention weights to a large negative number, such as $-10^{6}$, in order to make their contribution to gradients and values vanish in practice. This is done since linear algebra kernels and operators are heavily optimized for GPUs and it is faster to be slightly wasteful in computation rather than to have code with conditional (if then else) statements.

To [**illustrate how this function works**],
consider a minibatch of two examples of size $2 \times 4$,
where their valid lengths are $2$ and $3$, respectively.
As a result of the masked softmax operation,
values beyond the valid lengths for each pair of vectors are all masked as zero.

If we need more fine-grained control to specify the valid length for each of the two vectors of every example, we simply use a two-dimensional tensor of valid lengths. This yields:

#### Batch Matrix Multiplication

Another commonly used operation is to multiply batches of matrices by one another. This comes in handy when we have minibatches of queries, keys, and values. More specifically, assume that

Then the batch matrix multiplication (BMM) computes the elementwise product

Note that when applying this to a minibatch, we need the batch matrix multiplication introduced in . In the following implementation of the scaled dot product attention,
we use dropout for model regularization.

To [**illustrate how the `DotProductAttention` class works**],
we use the same keys, values, and valid lengths from the earlier toy example for additive attention. For the purpose of our example we assume that we have a minibatch size of $2$, a total of $10$ keys and values, and that the dimensionality of the values is $4$. Lastly, we assume that the valid length per observation is $2$ and $6$ respectively. Given that, we expect the output to be a $2 \times 1 \times 4$ tensor, i.e., one row per example of the minibatch.

Let's check whether the attention weights actually vanish for anything beyond the second and sixth column respectively (because of setting the valid length to $2$ and $6$).

### [**Additive Attention**]

When queries $\mathbf{q}$ and keys $\mathbf{k}$ are vectors of different dimension,
we can either use a matrix to address the mismatch via $\mathbf{q}^\top \mathbf{M} \mathbf{k}$, or we can use additive attention
as the scoring function. Another benefit is that, as its name indicates, the attention is additive. This can lead to some minor computational savings.
Given a query $\mathbf{q} \in \mathbb{R}^q$
and a key $\mathbf{k} \in \mathbb{R}^k$,
the *additive attention* scoring function  is given by

## The Bahdanau Attention Mechanism

When we encountered machine translation in ,
we designed an encoder--decoder architecture for sequence-to-sequence learning
based on two RNNs .
Specifically, the RNN encoder transforms a variable-length sequence
into a *fixed-shape* context variable.
Then, the RNN decoder generates the output (target) sequence token by token
based on the generated tokens and the context variable.

Recall  which we repeat () with some additional detail. Conventionally, in an RNN all relevant information about a source sequence is translated into some internal *fixed-dimensional* state representation by the encoder. It is this very state that is used by the decoder as the complete and exclusive source of information for generating the translated sequence. In other words, the sequence-to-sequence mechanism treats the intermediate state as a sufficient statistic of whatever string might have served as input.

While this is quite reasonable for short sequences, it is clear that it is infeasible for long ones, such as a book chapter or even just a very long sentence. After all, before too long there will simply not be enough "space" in the intermediate representation to store all that is important in the source sequence. Consequently the decoder will fail to translate long and complex sentences. One of the first to encounter this was  who tried to design an RNN to generate handwritten text. Since the source text has arbitrary length they designed a differentiable attention model
to align text characters with the much longer pen trace,
where the alignment moves only in one direction. This, in turn, draws on decoding algorithms in speech recognition, e.g., hidden Markov models .

Inspired by the idea of learning to align,
*without* the unidirectional alignment limitation.
When predicting a token,
if not all the input tokens are relevant,
the model aligns (or attends)
only to parts of the input sequence
that are deemed relevant to the current prediction. This is then used to update the current state before generating the next token. While quite innocuous in its description, this *Bahdanau attention mechanism* has arguably turned into one of the most influential ideas of the past decade in deep learning, giving rise to Transformers  and many related new architectures.

### Model

We follow the notation introduced by the sequence-to-sequence architecture of , in particular .
The key idea is that instead of keeping the state,
i.e., the context variable $\mathbf{c}$ summarizing the source sentence, as fixed, we dynamically update it, as a function of both the original text (encoder hidden states $\mathbf{h}_{t}$) and the text that was already generated (decoder hidden states $\mathbf{s}_{t'-1}$). This yields $\mathbf{c}_{t'}$, which is updated after any decoding time step $t'$. Suppose that the input sequence is of length $T$. In this case the context variable is the output of attention pooling:

## Multi-Head Attention

In practice, given the same set of queries, keys, and values we may want our model to combine knowledge from
different behaviors of the same attention mechanism,
such as capturing dependencies of various ranges
(e.g., shorter-range vs. longer-range) within a sequence.
Thus, it may be beneficial to allow our attention mechanism to jointly use different representation subspaces of queries, keys, and values.

To this end, instead of performing
a single attention pooling,
queries, keys, and values
can be transformed
with $h$ independently learned linear projections.
Then these $h$ projected queries, keys, and values
are fed into attention pooling in parallel.
In the end,
$h$ attention-pooling outputs
are concatenated and
transformed with another learned linear projection
to produce the final output.
This design
is called *multi-head attention*,
where each of the $h$ attention pooling outputs
is a *head* .
Using fully connected layers
to perform learnable linear transformations,
describes multi-head attention.

### Model

Before providing the implementation of multi-head attention,
let's formalize this model mathematically.
Given a query $\mathbf{q} \in \mathbb{R}^{d_q}$,
a key $\mathbf{k} \in \mathbb{R}^{d_k}$,
and a value $\mathbf{v} \in \mathbb{R}^{d_v}$,
each attention head $\mathbf{h}_i$  ($i = 1, \ldots, h$)
is computed as

Based on this design, each head may attend
to different parts of the input.
More sophisticated functions
than the simple weighted average can be expressed.

### Implementation

In our implementation,
we [**choose the scaled dot product attention
for each head**] of the multi-head attention.
To avoid significant growth of computational cost and parametrization cost,
we set $p_q = p_k = p_v = p_o / h$.
Note that $h$ heads can be computed in parallel
if we set the number of outputs
of linear transformations
for the query, key, and value
to $p_q h = p_k h = p_v h = p_o$.
In the following implementation,
$p_o$ is specified via the argument `num_hiddens`.

To allow for [**parallel computation of multiple heads**],
the above `MultiHeadAttention` class uses two transposition methods as defined below.
Specifically,
the `transpose_output` method reverses the operation
of the `transpose_qkv` method.

Let's [**test our implemented**] `MultiHeadAttention` class
using a toy example where keys and values are the same.
As a result,
the shape of the multi-head attention output
is (`batch_size`, `num_queries`, `num_hiddens`).

### Summary

Multi-head attention combines knowledge of the same attention pooling
via different representation subspaces of queries, keys, and values.
To compute multiple heads of multi-head attention in parallel,
proper tensor manipulation is needed.

### Exercises

1. Visualize attention weights of multiple heads in this experiment.
1. Suppose that we have a trained model based on multi-head attention and we want to prune less important attention heads to increase the prediction speed. How can we design experiments to measure the importance of an attention head?

[Discussions](https://discuss.d2l.ai/t/1634)

[Discussions](https://discuss.d2l.ai/t/1635)

[Discussions](https://discuss.d2l.ai/t/3869)

[Discussions](https://discuss.d2l.ai/t/18029)

## Self-Attention and Positional Encoding

In deep learning, we often use CNNs or RNNs to encode sequences.
Now with attention mechanisms in mind,
imagine feeding a sequence of tokens
into an attention mechanism
such that at every step,
each token has its own query, keys, and values.
Here, when computing the value of a token's representation at the next layer,
the token can attend (via its query vector) to any other's token
(matching based on their key vectors).
Using the full set of query-key compatibility scores,
we can compute, for each token, a representation
by building the appropriate weighted sum
over the other tokens.
Because every token is attending to each other token
(unlike the case where decoder steps attend to encoder steps),
such architectures are typically described as *self-attention* models ,
and elsewhere described as *intra-attention* model .
In this section, we will discuss sequence encoding using self-attention,
including using additional information for the sequence order.

### [**Self-Attention**]

Given a sequence of input tokens
$\mathbf{x}_1, \ldots, \mathbf{x}_n$ where any $\mathbf{x}_i \in \mathbb{R}^d$ ($1 \leq i \leq n$),
its self-attention outputs
a sequence of the same length
$\mathbf{y}_1, \ldots, \mathbf{y}_n$,
where

At first glance,
this trigonometric function
design looks weird.
Before we give explanations of this design,
let's first implement it in the following `PositionalEncoding` class.

In the positional embedding matrix $\mathbf{P}$,
[**rows correspond to positions within a sequence
and columns represent different positional encoding dimensions**].
In the example below,
we can see that
the $6^{\textrm{th}}$ and the $7^{\textrm{th}}$
columns of the positional embedding matrix
have a higher frequency than
the $8^{\textrm{th}}$ and the $9^{\textrm{th}}$
columns.
The offset between
the $6^{\textrm{th}}$ and the $7^{\textrm{th}}$ (same for the $8^{\textrm{th}}$ and the $9^{\textrm{th}}$) columns
is due to the alternation of sine and cosine functions.

#### Absolute Positional Information

To see how the monotonically decreased frequency
along the encoding dimension relates to absolute positional information,
let's print out [**the binary representations**] of $0, 1, \ldots, 7$.
As we can see, the lowest bit, the second-lowest bit,
and the third-lowest bit alternate on every number,
every two numbers, and every four numbers, respectively.

In binary representations, a higher bit
has a lower frequency than a lower bit.
Similarly, as demonstrated in the heat map below,
[**the positional encoding decreases
frequencies along the encoding dimension**]
by using trigonometric functions.
Since the outputs are float numbers,
such continuous representations
are more space-efficient
than binary representations.

#### Relative Positional Information

Besides capturing absolute positional information,
the above positional encoding
also allows
a model to easily learn to attend by relative positions.
This is because
for any fixed position offset $\delta$,
the positional encoding at position $i + \delta$
can be represented by a linear projection
of that at position $i$.

This projection can be explained
mathematically.
Denoting
$\omega_j = 1/10000^{2j/d}$,
any pair of $(p_{i, 2j}, p_{i, 2j+1})$
in
can
be linearly projected to $(p_{i+\delta, 2j}, p_{i+\delta, 2j+1})$
for any fixed offset $\delta$:

## The Transformer Architecture

We have compared CNNs, RNNs, and self-attention in
Notably, self-attention
enjoys both parallel computation and
the shortest maximum path length.
Therefore,
it is appealing to design deep architectures
by using self-attention.
Unlike earlier self-attention models
that still rely on RNNs for input representations ,
the Transformer model
is solely based on attention mechanisms
without any convolutional or recurrent layer .
Though originally proposed
for sequence-to-sequence learning on text data,
Transformers have been
pervasive in a wide range of
modern deep learning applications,
such as in areas to do with language, vision, speech, and reinforcement learning.

### Model

As an instance of the encoder--decoder
architecture,
the overall architecture of
the Transformer
is presented in .
As we can see,
the Transformer is composed of an encoder and a decoder.
In contrast to
Bahdanau attention
for sequence-to-sequence learning
in ,
the input (source) and output (target)
sequence embeddings
are added with positional encoding
before being fed into
the encoder and the decoder
that stack modules based on self-attention.

Now we provide an overview of the
Transformer architecture in .
At a high level,
the Transformer encoder is a stack of multiple identical layers,
where each layer
has two sublayers (either is denoted as $\textrm{sublayer}$).
The first
is a multi-head self-attention pooling
and the second is a positionwise feed-forward network.
Specifically,
in the encoder self-attention,
queries, keys, and values are all from the
outputs of the previous encoder layer.
Inspired by the ResNet design of ,
a residual connection is employed
around both sublayers.
In the Transformer,
for any input $\mathbf{x} \in \mathbb{R}^d$ at any position of the sequence,
we require that $\textrm{sublayer}(\mathbf{x}) \in \mathbb{R}^d$ so that
the residual connection $\mathbf{x} + \textrm{sublayer}(\mathbf{x}) \in \mathbb{R}^d$ is feasible.
This addition from the residual connection is immediately
followed by layer normalization .
As a result, the Transformer encoder outputs a $d$-dimensional vector representation
for each position of the input sequence.

The Transformer decoder is also a stack of multiple identical layers
with residual connections and layer normalizations.
As well as the two sublayers described in
the encoder, the decoder inserts
a third sublayer, known as
the encoder--decoder attention,
between these two.
In the encoder--decoder attention,
queries are from the
outputs of the decoder's self-attention sublayer,
and the keys and values are
from the Transformer encoder outputs.
In the decoder self-attention,
queries, keys, and values are all from the
outputs of the previous decoder layer.
However, each position in the decoder is
allowed only to attend to all positions in the decoder
up to that position.
This *masked* attention
preserves the autoregressive property,
ensuring that the prediction only depends
on those output tokens that have been generated.

We have already described and implemented
multi-head attention based on scaled dot products
in
and positional encoding in .
In the following, we will implement
the rest of the Transformer model.

### [**Positionwise Feed-Forward Networks**]

The positionwise feed-forward network transforms
the representation at all the sequence positions
using the same MLP.
This is why we call it *positionwise*.
In the implementation below,
the input `X` with shape
(batch size, number of time steps or sequence length in tokens,
number of hidden units or feature dimension)
will be transformed by a two-layer MLP into
an output tensor of shape
(batch size, number of time steps, `ffn_num_outputs`).

The following example
shows that [**the innermost dimension
of a tensor changes**] to
the number of outputs in
the positionwise feed-forward network.
Since the same MLP transforms
at all the positions,
when the inputs at all these positions are the same,
their outputs are also identical.

### Residual Connection and Layer Normalization

Now let's focus on the "add & norm" component in .
As we described at the beginning of this section,
this is a residual connection immediately
followed by layer normalization.
Both are key to effective deep architectures.

In ,
we explained how batch normalization
recenters and rescales across the examples within
a minibatch.
As discussed in ,
layer normalization is the same as batch normalization
except that the former
normalizes across the feature dimension,
thus enjoying benefits of scale independence and batch size independence.
Despite its pervasive applications
in computer vision,
batch normalization
is usually empirically
less effective than layer normalization
in natural language processing
tasks, where the inputs are often
variable-length sequences.

The following code snippet
[**compares the normalization across different dimensions
by layer normalization and batch normalization**].

Now we can implement the `AddNorm` class
[**using a residual connection followed by layer normalization**].
Dropout is also applied for regularization.

The residual connection requires that
the two inputs are of the same shape
so that [**the output tensor also has the same shape after the addition operation**].

### Encoder

With all the essential components to assemble
the Transformer encoder,
let's start by
implementing [**a single layer within the encoder**].
The following `TransformerEncoderBlock` class
contains two sublayers: multi-head self-attention and positionwise feed-forward networks,
where a residual connection followed by layer normalization is employed
around both sublayers.

As we can see,
[**no layer in the Transformer encoder
changes the shape of its input.**]

In the following [**Transformer encoder**] implementation,
we stack `num_blks` instances of the above `TransformerEncoderBlock` classes.
Since we use the fixed positional encoding
whose values are always between $-1$ and $1$,
we multiply values of the learnable input embeddings
by the square root of the embedding dimension
to rescale before summing up the input embedding and the positional encoding.

Below we specify hyperparameters to [**create a two-layer Transformer encoder**].
The shape of the Transformer encoder output
is (batch size, number of time steps, `num_hiddens`).

### Decoder

As shown in ,
[**the Transformer decoder
is composed of multiple identical layers**].
Each layer is implemented in the following
`TransformerDecoderBlock` class,
which contains three sublayers:
decoder self-attention,
encoder--decoder attention,
and positionwise feed-forward networks.
These sublayers employ
a residual connection around them
followed by layer normalization.

As we described earlier in this section,
in the masked multi-head decoder self-attention
(the first sublayer),
queries, keys, and values
all come from the outputs of the previous decoder layer.
When training sequence-to-sequence models,
tokens at all the positions (time steps)
of the output sequence
are known.
However,
during prediction
the output sequence is generated token by token;
thus,
at any decoder time step
only the generated tokens
can be used in the decoder self-attention.
To preserve autoregression in the decoder,
its masked self-attention
specifies  `dec_valid_lens` so that
any query
only attends to
all positions in the decoder
up to the query position.

To facilitate scaled dot product operations
in the encoder--decoder attention
and addition operations in the residual connections,
[**the feature dimension (`num_hiddens`) of the decoder is
the same as that of the encoder.**]

Now we [**construct the entire Transformer decoder**]
composed of `num_blks` instances of `TransformerDecoderBlock`.
In the end,
a fully connected layer computes the prediction
for all the `vocab_size` possible output tokens.
Both of the decoder self-attention weights
and the encoder--decoder attention weights
are stored for later visualization.

### [**Training**]

Let's instantiate an encoder--decoder model
by following the Transformer architecture.
Here we specify that
both the Transformer encoder and the Transformer decoder
have two layers using 4-head attention.
As in ,
we train the Transformer model
for sequence-to-sequence learning on the English--French machine translation dataset.

After training,
we use the Transformer model
to [**translate a few English sentences**] into French and compute their BLEU scores.

Let's [**visualize the Transformer attention weights**] when translating the final English sentence into French.
The shape of the encoder self-attention weights
is (number of encoder layers, number of attention heads, `num_steps` or number of queries, `num_steps` or number of key-value pairs).

In the encoder self-attention,
both queries and keys come from the same input sequence.
Since padding tokens do not carry meaning,
with specified valid length of the input sequence
no query attends to positions of padding tokens.
In the following,
two layers of multi-head attention weights
are presented row by row.
Each head independently attends
based on a separate representation subspace of queries, keys, and values.

[**To visualize the decoder self-attention weights and the encoder--decoder attention weights,
we need more data manipulations.**]
For example,
we fill the masked attention weights with zero.
Note that
the decoder self-attention weights
and the encoder--decoder attention weights
both have the same queries:
the beginning-of-sequence token followed by
the output tokens and possibly
end-of-sequence tokens.

Because of the autoregressive property of the decoder self-attention,
no query attends to key--value pairs after the query position.

Similar to the case in the encoder self-attention,
via the specified valid length of the input sequence,
[**no query from the output sequence
attends to those padding tokens from the input sequence.**]

Although the Transformer architecture
was originally proposed for sequence-to-sequence learning,
as we will discover later in the book,
either the Transformer encoder
or the Transformer decoder
is often individually used
for different deep learning tasks.

### Summary

The Transformer is an instance of the encoder--decoder architecture,
though either the encoder or the decoder can be used individually in practice.
In the Transformer architecture, multi-head self-attention is used
for representing the input sequence and the output sequence,
though the decoder has to preserve the autoregressive property via a masked version.
Both the residual connections and the layer normalization in the Transformer
are important for training a very deep model.
The positionwise feed-forward network in the Transformer model
transforms the representation at all the sequence positions using the same MLP.

### Exercises

1. Train a deeper Transformer in the experiments. How does it affect the training speed and the translation performance?
1. Is it a good idea to replace scaled dot product attention with additive attention in the Transformer? Why?
1. For language modeling, should we use the Transformer encoder, decoder, or both? How would you design this method?
1. What challenges can Transformers face if input sequences are very long? Why?
1. How would you improve the computational and memory efficiency of Transformers? Hint: you may refer to the survey paper by .

[Discussions](https://discuss.d2l.ai/t/348)

[Discussions](https://discuss.d2l.ai/t/1066)

[Discussions](https://discuss.d2l.ai/t/3871)

[Discussions](https://discuss.d2l.ai/t/18031)

## Large-Scale Pretraining with Transformers

So far in our image classification and machine translation experiments,
models have been trained on datasets with input--output examples
*from scratch* to perform specific tasks.
For example, a Transformer was trained
with English--French pairs ()
so that this model can translate input English text into French.
As a result, each model becomes a *specific expert*
that is sensitive to even a slight shift in data distribution
().
For better generalized models, or even more competent *generalists*
that can perform multiple tasks with or without adaptation,
*pretraining* models on large data has been increasingly common.

Given larger data for pretraining, the Transformer architecture
performs better with an increased model size and training compute,
demonstrating superior *scaling* behavior.
Specifically, performance of Transformer-based language models
scales as a power law with the amount of model parameters,
training tokens, and training compute .
The scalability of Transformers is also evidenced
by the significantly boosted performance
from larger vision Transformers trained on larger data
(discussed in ).
More recent success stories include Gato, a *generalist* model
that can play Atari, caption images, chat, and act as a robot . Gato is a single  Transformer that scales well when pretrained on diverse modalities,
including text, images, joint torques, and button presses.
Notably, all such multimodal data is serialized into a flat sequence of tokens,
which can be processed akin to text tokens ()
or image patches () by Transformers.

Prior to the compelling success of pretraining Transformers for multimodal data,
Transformers were extensively pretrained  with a wealth of text.
Originally proposed for machine translation,
the Transformer architecture in
consists of an encoder for representing input sequences
and a decoder for generating target sequences.
Primarily, Transformers can be used in three different modes:
*encoder-only*, *encoder--decoder*, and *decoder-only*.
To conclude this chapter, we will review these three modes
and explain the scalability in pretraining Transformers.

### Encoder-Only

When only the Transformer encoder is used,
a sequence of input tokens is converted
into the same number of representations
that can be further projected into output
(e.g., classification). A Transformer encoder
consists of  self-attention layers,
where all input tokens attend to each other.
For example, vision Transformers depicted in
are encoder-only, converting a sequence of input image patches into
the representation of a special “&lt;cls&gt;” token.
Since this representation depends on all input tokens,
it is further projected into classification labels.
This design was inspired by an earlier encoder-only Transformer
pretrained on text: BERT (Bidirectional Encoder Representations from Transformers) .

#### Pretraining BERT

BERT is pretrained on text sequences using *masked language modeling*:
input text with randomly masked tokens is fed
into a Transformer encoder to predict the masked tokens.
As illustrated in ,
an original text sequence "I", "love", "this", "red", "car"
is prepended with the “&lt;cls&gt;” token, and the “&lt;mask&gt;” token
randomly replaces "love"; then the cross-entropy loss between the masked token "love"
and its prediction is to be minimized during pretraining.
Note that there is no constraint in the attention pattern of Transformer encoders
(right of )
so all tokens can attend to each other.
Thus, prediction of "love" depends on input tokens before and after it in the sequence.
This is why BERT is a "bidirectional encoder".
Without need for manual labeling, large-scale text data
from books and Wikipedia can be used for pretraining BERT.

#### Fine-Tuning BERT

The pretrained BERT can be *fine-tuned* to downstream encoding tasks involving single text or text pairs. During fine-tuning, additional layers can be added to BERT with randomized parameters: these parameters and those pretrained BERT parameters will be *updated* to fit training data of downstream tasks.

fine-tuning of BERT for sentiment analysis.
The Transformer encoder is a pretrained BERT,
which takes a text sequence as input
and feeds the “&lt;cls&gt;” representation
(global representation of the input)
into an additional fully connected layer
to predict the sentiment.
During fine-tuning, the cross-entropy loss
between the prediction and the label
on sentiment analysis data
is minimized via gradient-based algorithms,
where the additional layer is trained from scratch
while pretrained parameters of BERT are updated.
BERT does more than sentiment analysis.
The general language representations learned
by the 350-million-parameter BERT
from 250 billion training tokens
advanced the state of the art for natural language tasks
such as single text classification,
text pair classification or regression,
text tagging, and question answering.

You may note that these downstream tasks include text pair understanding.
BERT pretraining has another loss for predicting
whether one sentence immediately follows the other.
However, this loss was later found to be less useful when pretraining RoBERTa,
a BERT variant of the same size, on 2000 billion tokens .
Other derivatives of BERT improved model architectures or pretraining objectives,
such as ALBERT (enforcing parameter sharing) ,
SpanBERT (representing and predicting spans of text) ,
DistilBERT (lightweight via knowledge distillation) ,
and ELECTRA (replaced token detection) .
Moreover, BERT inspired Transformer pretraining in computer vision,
such as with vision Transformers ,
Swin Transformers ,
and MAE (masked autoencoders) .

### Encoder--Decoder

Since a Transformer encoder converts a sequence of input tokens
into the same number of output representations,
the encoder-only mode cannot generate a sequence of arbitrary length as in machine translation.
As originally proposed for machine translation,
the Transformer architecture can be outfitted with a decoder
that autoregressively predicts the target sequence
of arbitrary length, token by token,
conditional on both encoder output and decoder output:
(i) for conditioning on encoder output, encoder--decoder cross-attention
(multi-head attention of decoder in )
allows target tokens to attend to *all* input tokens;
(ii) conditioning on decoder output is achieved
by a so-called *causal* attention
(this name is common in the literature but is misleading
as it has little connection to the proper study of causality)
pattern (masked multi-head attention of decoder in ),
where any target token can only attend to *past* and *present* tokens in the target sequence.

To pretrain encoder--decoder Transformers beyond human-labeled machine translation data,
BART  and T5
are two concurrently proposed encoder--decoder Transformers
pretrained on large-scale text corpora.
Both attempt to reconstruct original text in their pretraining objectives,
while the former emphasizes noising input
(e.g., masking, deletion, permutation, and rotation)
and the latter highlights multitask unification
with comprehensive ablation studies.

#### Pretraining T5

As an example of the pretrained Transformer encoder--decoder,
T5 (Text-to-Text Transfer Transformer)
unifies many tasks as the same text-to-text problem:
for any task, the input of the encoder is a task description
(e.g., "Summarize", ":") followed by task input
(e.g., a sequence of tokens from an article),
and the decoder predicts the task output
(e.g., a sequence of tokens summarizing the input article).
To perform as text-to-text, T5 is trained
to generate some target text conditional on input text.

To obtain input and output from any original text,
T5 is pretrained to predict consecutive spans.
Specifically, tokens from text are randomly replaced
by special tokens where each consecutive span
is replaced by the same special token.
Consider the example in ,
where the original text is "I", "love", "this", "red", "car".
Tokens "love", "red", "car" are randomly replaced by special tokens.
Since "red" and "car" are a consecutive span,
they are replaced by the same special token.
As a result, the input sequence is "I", "&lt;X&gt;", "this", "&lt;Y&gt;",
and the target sequence is
"&lt;X&gt;", "love", "&lt;Y&gt;", "red", "car", "&lt;Z&gt;",
where "&lt;Z&gt;" is another special token marking the end.
As shown in ,
the decoder has a causal attention pattern to prevent itself
from attending to future tokens during sequence prediction.

In T5, predicting consecutive span is also referred to
as reconstructing corrupted text.
With this objective, T5 is pretrained
with 1000 billion tokens from the C4
(Colossal Clean Crawled Corpus) data,
which consists of clean English text
from the web .

#### Fine-Tuning T5

Similar to BERT, T5 needs to be fine-tuned (updating T5 parameters)
on task-specific training data to perform this task.
Major differences from BERT fine-tuning include:
(i) T5 input includes task descriptions;
(ii) T5 can generate sequences
with arbitrary length
with its Transformer decoder;
(iii) No additional layers are required.

explains fine-tuning T5
using text summarization as an example.
In this downstream task,
the task description tokens "Summarize", ":"
followed by the article tokens are input to the encoder.

After fine-tuning, the 11-billion-parameter T5 (T5-11B)
achieved state-of-the-art results on multiple encoding (e.g., classification)
and generation (e.g., summarization) benchmarks.
Since released, T5 has been extensively used in later research.
For example, switch Transformers are designed based on T5
to activate a subset of the parameters
for better computational efficiency .
In a text-to-image model called Imagen,
text is input to a frozen T5 encoder (T5-XXL)
with 4.6 billion parameters .
The photorealistic text-to-image examples in
suggest that the T5 encoder alone may effectively
represent text even without fine-tuning.

### Decoder-Only

We have reviewed encoder-only and encoder--decoder Transformers.
Alternatively, decoder-only Transformers
remove the entire encoder and the decoder sublayer
with the encoder--decoder cross-attention
from the original encoder--decoder architecture
depicted in .
Nowadays, decoder-only Transformers have been the *de facto* architecture
in large-scale language modeling (),
which leverages the world's abundant unlabeled text corpora via self-supervised learning.

#### GPT and GPT-2

Using language modeling as the training objective,
the GPT (generative pre-training) model
chooses a Transformer decoder
as its backbone .

Following the autoregressive language model training
as described in ,
GPT pretraining with a Transformer encoder,
where the target sequence is the input sequence shifted by one token.
Note that the attention pattern in the Transformer decoder
enforces that each token can only attend to its past tokens
(future tokens cannot be attended to because they have not yet been chosen).

GPT has 100 million parameters and needs to be
fine-tuned for individual downstream tasks.
A much larger Transformer-decoder language model,
GPT-2, was introduced one year later .
Compared with the original Transformer decoder in GPT, pre-normalization
(discussed in )
and improved initialization and weight-scaling were adopted in GPT-2.
Pretrained on 40 GB of text, the 1.5-billion-parameter
GPT-2 obtained the state-of-the-art results on language modeling benchmarks
and promising results on multiple other tasks
*without updating the parameters or architecture*.

#### GPT-3 and Beyond

GPT-2 demonstrated potential of using the same language model
for multiple tasks without updating the model.
This is more computationally efficient than fine-tuning,
which requires model updates via gradient computation.

Before explaining the more computationally efficient use
of language models without parameter update,
recall  that a language model
can be trained to generate a text sequence
conditional on some prefix text sequence.
Thus, a pretrained language model may generate the task output
as a sequence *without parameter update*,
conditional on an input sequence with the task description,
task-specific input--output examples, and a prompt (task input).
This learning paradigm is called *in-context learning* ,
which can be further categorized
into *zero-shot*, *one-shot*, and *few-shot*,
when there is no, one, and a few task-specific input--output examples ().

These three settings were tested in GPT-3 ,
whose largest version uses data and model size
about two orders of magnitude larger than those in GPT-2.
GPT-3 uses the same Transformer decoder architecture
as its direct predecessor GPT-2
except that attention patterns
(at the right in )
are sparser at alternating layers.
Pretrained with 300 billion tokens,
GPT-3 performs better with larger model size,
where few-shot performance increases most rapidly ().

The subsequent GPT-4 model did not fully disclose technical details in its report .
By contrast with its predecessors, GPT-4
is a large-scale, multimodal model that
can take both text and images as input
and generate text output.

### Scalability

of Transformers in the GPT-3 language model.
For language modeling, more comprehensive empirical studies
on the scalability of Transformers have led researchers to see promise
in training larger Transformers with more data and compute .

As shown in ,
*power-law scaling* can be observed in the performance
with respect to the model size (number of parameters, excluding embedding layers),
dataset size (number of training tokens),
and amount of training compute (PetaFLOP/s-days, excluding embedding layers).
In general, increasing all these three factors in tandem leads to better performance.
However, *how* to increase them in tandem
still remains a matter of debate .

As well as increased performance, large models also enjoy better sample efficiency than small models.  shows that large models need fewer training samples (tokens processed) to perform at the same level achieved by small models, and performance is scaled smoothly with compute.

The empirical scaling behaviors in  have been tested in subsequent large Transformer models. For example, GPT-3 supported this hypothesis with two more orders of magnitude in .

### Large Language Models

The scalability of Transformers in the GPT series has inspired subsequent large language models.
The GPT-2 Transformer decoder was used for training the 530-billion-parameter Megatron-Turing NLG  with 270 billion training tokens. Following the GPT-2 design, the 280-billion-parameter Gopher  pretrained with 300 billion tokens, performed competitively across diverse tasks.
Inheriting the same architecture and using the same compute budget of Gopher, Chinchilla  is a substantially smaller (70 billion parameters) model that trains for much longer (1.4 trillion training tokens), outperforming Gopher on many tasks and with more emphasis on the number of tokens than on the number of parameters.
To continue the scaling line of language modeling,
PaLM (Pathway Language Model) , a 540-billion-parameter Transformer decoder with modified designs pretrained on 780 billion tokens, outperformed average human performance on the BIG-Bench benchmark . Its later version, PaLM 2 , scaled data and model roughly 1:1 and improved multilingual and reasoning capabilities.
Other large language models, such as Minerva   that further trains a generalist (PaLM) and Galactica  that is not trained on a general corpus, have shown promising quantitative and scientific reasoning capabilities.

Open-sourced releases, such as OPT (Open Pretrained Transformers) , BLOOM , and FALCON ,
democratized research and use of large language models.
Focusing on computational efficiency at inference time,
the open-sourced Llama 1  outperformed much larger models by training on more tokens than had been typically used. The updated Llama 2  further increased the pretraining corpus by 40%, leading to product models that may match the performance of competitive close-sourced models.

However, simply increasing model size does not inherently make models follow human instructions better.
on a range of datasets described via *instructions*
can improve zero-shot performance on held-out tasks.
Using *reinforcement learning from human feedback*,
to follow a diverse set of instructions.
Following the resultant InstructGPT which
aligns language models with human intent
via fine-tuning ,
[ChatGPT](https://chat.openai.com/)
can generate human-like responses (e.g., code debugging and creative writing)
based on conversations with humans
and can perform many natural language processing
tasks zero-shot .
to partially automate the instruction tuning process, which is also known as *reinforcement learning from AI feedback*.

Large language models offer an exciting prospect
of formulating text input to induce models to perform desired tasks via in-context learning,
which is also known as *prompting*.
Notably,
*chain-of-thought prompting* ,
an in-context learning method
with few-shot "question, intermediate reasoning steps, answer" demonstrations,
elicits the complex reasoning capabilities of
large language models
in order to solve mathematical, commonsense, and symbolic reasoning tasks.
Sampling multiple reasoning paths , diversifying few-shot demonstrations ,
and reducing complex problems to sub-problems
can all improve the reasoning accuracy. In fact, with simple prompts like "Let's think step by step" just before each answer,
large language models can even perform *zero-shot*
chain-of-thought reasoning with decent accuracy .
Even for multimodal inputs consisting of both text and images,
language models can perform multimodal chain-of-thought reasoning with higher accuracy than using text input only .

### Summary and Discussion

Transformers have been pretrained as encoder-only (e.g., BERT), encoder--decoder (e.g., T5), and decoder-only (e.g., GPT series). Pretrained models may be adapted to perform different tasks with model update (e.g., fine-tuning) or not (e.g., few-shot). Scalability of Transformers suggests that better performance benefits from larger models, more training data, and more training compute. Since Transformers were first designed and pretrained for text data, this section leans slightly towards natural language processing. Nonetheless, those models discussed above can be often found in more recent models across multiple modalities. For example,
(i) Chinchilla  was further extended to Flamingo , a visual language model for few-shot learning;
(ii) GPT-2  and the vision Transformer encode text and images in CLIP (Contrastive Language-Image Pre-training) , whose image and text embeddings were later adopted in the DALL-E 2 text-to-image system . Although there have been no systematic studies on Transformer scalability in multimodal pretraining yet, an all-Transformer text-to-image model called Parti  shows potential of scalability across modalities:
a larger Parti is more capable of high-fidelity image generation and content-rich text understanding ().

### Exercises

1. Is it possible to fine-tune T5 using a minibatch consisting of different tasks? Why or why not? How about for GPT-2?
1. Given a powerful language model, what applications can you think of?
1. Say that you are asked to fine-tune a language model to perform text classification by adding additional layers. Where will you add them? Why?
1. Consider sequence-to-sequence problems (e.g., machine translation) where the input sequence is always available throughout the target sequence prediction. What could be limitations of modeling with decoder-only Transformers? Why?

[Discussions](https://discuss.d2l.ai/t/9232)

# Optimization Algorithms

If you read the book in sequence up to this point you already used a number of optimization algorithms to train deep learning models.
They were the tools that allowed us to continue updating model parameters and to minimize the value of the loss function, as evaluated on the training set. Indeed, anyone content with treating optimization as a black box device to minimize objective functions in a simple setting might well content oneself with the knowledge that there exists an array of incantations of such a procedure (with names such as "SGD" and "Adam").

To do well, however, some deeper knowledge is required.
Optimization algorithms are important for deep learning.
On the one hand, training a complex deep learning model can take hours, days, or even weeks.
The performance of the optimization algorithm directly affects the model's training efficiency.
On the other hand, understanding the principles of different optimization algorithms and the role of their hyperparameters
will enable us to tune the hyperparameters in a targeted manner to improve the performance of deep learning models.

In this chapter, we explore common deep learning optimization algorithms in depth.
Almost all optimization problems arising in deep learning are *nonconvex*.
Nonetheless, the design and analysis of algorithms in the context of *convex* problems have proven to be very instructive.
It is for that reason that this chapter includes a primer on convex optimization and the proof for a very simple stochastic gradient descent algorithm on a convex objective function.

## Optimization and Deep Learning

In this section, we will discuss the relationship between optimization and deep learning as well as the challenges of using optimization in deep learning.
For a deep learning problem, we will usually define a *loss function* first. Once we have the loss function, we can use an optimization algorithm in attempt to minimize the loss.
In optimization, a loss function is often referred to as the *objective function* of the optimization problem. By tradition and convention most optimization algorithms are concerned with *minimization*. If we ever need to maximize an objective there is a simple solution: just flip the sign on the objective.

### Goal of Optimization

Although optimization provides a way to minimize the loss function for deep
learning, in essence, the goals of optimization and deep learning are
fundamentally different.
The former is primarily concerned with minimizing an
objective whereas the latter is concerned with finding a suitable model, given a
finite amount of data.
In ,
we discussed the difference between these two goals in detail.
For instance,
training error and generalization error generally differ: since the objective
function of the optimization algorithm is usually a loss function based on the
training dataset, the goal of optimization is to reduce the training error.
However, the goal of deep learning (or more broadly, statistical inference) is to
reduce the generalization error.
To accomplish the latter we need to pay
attention to overfitting in addition to using the optimization algorithm to
reduce the training error.

To illustrate the aforementioned different goals,
let's consider
the empirical risk and the risk.
As described
in ,
the empirical risk
is an average loss
on the training dataset
while the risk is the expected loss
on the entire population of data.
Below we define two functions:
the risk function `f`
and the empirical risk function `g`.
Suppose that we have only a finite amount of training data.
As a result, here `g` is less smooth than `f`.

The graph below illustrates that the minimum of the empirical risk on a training dataset may be at a different location from the minimum of the risk (generalization error).

### Optimization Challenges in Deep Learning

In this chapter, we are going to focus specifically on the performance of optimization algorithms in minimizing the objective function, rather than a
model's generalization error.
In
we distinguished between analytical solutions and numerical solutions in
optimization problems.
In deep learning, most objective functions are
complicated and do not have analytical solutions. Instead, we must use numerical
optimization algorithms.
The optimization algorithms in this chapter
all fall into this
category.

There are many challenges in deep learning optimization. Some of the most vexing ones are local minima, saddle points, and vanishing gradients.
Let's have a look at them.

#### Local Minima

For any objective function $f(x)$,
if the value of $f(x)$ at $x$ is smaller than the values of $f(x)$ at any other points in the vicinity of $x$, then $f(x)$ could be a local minimum.
If the value of $f(x)$ at $x$ is the minimum of the objective function over the entire domain,
then $f(x)$ is the global minimum.

For example, given the function

## Convexity

Convexity plays a vital role in the design of optimization algorithms.
This is largely due to the fact that it is much easier to analyze and test algorithms in such a context.
In other words,
if the algorithm performs poorly even in the convex setting,
typically we should not hope to see great results otherwise.
Furthermore, even though the optimization problems in deep learning are generally nonconvex, they often exhibit some properties of convex ones near local minima. This can lead to exciting new optimization variants such as .

### Definitions

Before convex analysis,
we need to define *convex sets* and *convex functions*.
They lead to mathematical tools that are commonly applied to machine learning.

#### Convex Sets

Sets are the basis of convexity. Simply put, a set $\mathcal{X}$ in a vector space is *convex* if for any $a, b \in \mathcal{X}$ the line segment connecting $a$ and $b$ is also in $\mathcal{X}$. In mathematical terms this means that for all $\lambda \in [0, 1]$ we have

To illustrate this let's plot a few functions and check which ones satisfy the requirement.
Below we define a few functions, both convex and nonconvex.

As expected, the cosine function is *nonconvex*, whereas the parabola and the exponential function are. Note that the requirement that $\mathcal{X}$ is a convex set is necessary for the condition to make sense. Otherwise the outcome of $f(\lambda x + (1-\lambda) x')$ might not be well defined.

#### Jensen's Inequality

Given a convex function $f$,
one of the most useful mathematical tools
is *Jensen's inequality*.
It amounts to a generalization of the definition of convexity:

since $\int P(Y) P(X \mid Y) dY = P(X)$.
This can be used in variational methods. Here $Y$ is typically the unobserved random variable, $P(Y)$ is the best guess of how it might be distributed, and $P(X)$ is the distribution with $Y$ integrated out. For instance, in clustering $Y$ might be the cluster labels and $P(X \mid Y)$ is the generative model when applying cluster labels.

### Properties

Convex functions have many useful properties. We describe a few commonly-used ones below.

#### Local Minima Are Global Minima

First and foremost, the local minima of convex functions are also the global minima.
We can prove it by contradiction as follows.

Consider a convex function $f$ defined on a convex set $\mathcal{X}$.
Suppose that $x^{\ast} \in \mathcal{X}$ is a local minimum:
there exists a small positive value $p$ so that for $x \in \mathcal{X}$ that satisfies $0 < |x - x^{\ast}| \leq p$ we have $f(x^{\ast}) < f(x)$.

Assume that the local minimum $x^{\ast}$
is not the global minimum of $f$:
there exists $x' \in \mathcal{X}$ for which $f(x') < f(x^{\ast})$.
There also exists
$\lambda \in [0, 1)$ such as $\lambda = 1 - \frac{p}{|x^{\ast} - x'|}$
so that
$0 < |\lambda x^{\ast} + (1-\lambda) x' - x^{\ast}| \leq p$.

However,
according to the definition of convex functions, we have

is convex.

Let's prove this quickly. Recall that for any $x, x' \in \mathcal{S}_b$ we need to show that $\lambda x + (1-\lambda) x' \in \mathcal{S}_b$ as long as $\lambda \in [0, 1]$.
Since $f(x) \leq b$ and $f(x') \leq b$,
by the definition of convexity we have

Since the second derivative is given by the limit over finite differences it follows that

By monotonicity $f'(\beta) \geq f'(\alpha)$, hence

thus proving convexity.

Second, we need a lemma before
proving the multidimensional case:
$f: \mathbb{R}^n \rightarrow \mathbb{R}$
is convex if and only if for all $\mathbf{x}, \mathbf{y} \in \mathbb{R}^n$

=&f\left(\left(\lambda a + (1-\lambda) b\right)\mathbf{x} + \left(1-\lambda a - (1-\lambda) b\right)\mathbf{y} \right)\\
=&f\left(\lambda \left(a \mathbf{x} + (1-a)  \mathbf{y}\right)  + (1-\lambda) \left(b \mathbf{x} + (1-b)  \mathbf{y}\right) \right)\\
\leq& \lambda f\left(a \mathbf{x} + (1-a)  \mathbf{y}\right)  + (1-\lambda) f\left(b \mathbf{x} + (1-b)  \mathbf{y}\right) \\
=& \lambda g(a) + (1-\lambda) g(b).
\end{aligned}$$

To prove the converse,
we can show that for
all $\lambda \in [0, 1]$

    \textrm{ subject to } & c_i(\mathbf{x}) \leq 0 \textrm{ for all } i \in \{1, \ldots, n\},
\end{aligned}$$

where $f$ is the objective and the functions $c_i$ are constraint functions. To see what this does consider the case where $c_1(\mathbf{x}) = \|\mathbf{x}\|_2 - 1$. In this case the parameters $\mathbf{x}$ are constrained to the unit ball. If a second constraint is $c_2(\mathbf{x}) = \mathbf{v}^\top \mathbf{x} + b$, then this corresponds to all $\mathbf{x}$ lying on a half-space. Satisfying both constraints simultaneously amounts to selecting a slice of a ball.

#### Lagrangian

In general, solving a constrained optimization problem is difficult. One way of addressing it stems from physics with a rather simple intuition. Imagine a ball inside a box. The ball will roll to the place that is lowest and the forces of gravity will be balanced out with the forces that the sides of the box can impose on the ball. In short, the gradient of the objective function (i.e., gravity) will be offset by the gradient of the constraint function (the ball need to remain inside the box by virtue of the walls "pushing back").
Note that some constraints may not be active:
the walls that are not touched by the ball
will not be able to exert any force on the ball.

Skipping over the derivation of the *Lagrangian* $L$,
the above reasoning
can be expressed via the following saddle point optimization problem:

This turns out to be a *projection* of $\mathbf{g}$ onto the ball of radius $\theta$. More generally, a projection on a convex set $\mathcal{X}$ is defined as

## Gradient Descent

In this section we are going to introduce the basic concepts underlying *gradient descent*.
Although it is rarely used directly in deep learning, an understanding of gradient descent is key to understanding stochastic gradient descent algorithms.
For instance, the optimization problem might diverge due to an overly large learning rate. This phenomenon can already be seen in gradient descent. Likewise, preconditioning is a common technique in gradient descent and carries over to more advanced algorithms.
Let's start with a simple special case.

### One-Dimensional Gradient Descent

Gradient descent in one dimension is an excellent example to explain why the gradient descent algorithm may reduce the value of the objective function. Consider some continuously differentiable real-valued function $f: \mathbb{R} \rightarrow \mathbb{R}$. Using a Taylor expansion we obtain

If the derivative $f'(x) \neq 0$ does not vanish we make progress since $\eta f'^2(x)>0$. Moreover, we can always choose $\eta$ small enough for the higher-order terms to become irrelevant. Hence we arrive at

to iterate $x$, the value of function $f(x)$ might decline. Therefore, in gradient descent we first choose an initial value $x$ and a constant $\eta > 0$ and then use them to continuously iterate $x$ until the stop condition is reached, for example, when the magnitude of the gradient $|f'(x)|$ is small enough or the number of iterations has reached a certain value.

For simplicity we choose the objective function $f(x)=x^2$ to illustrate how to implement gradient descent. Although we know that $x=0$ is the solution to minimize $f(x)$, we still use this simple function to observe how $x$ changes.

Next, we use $x=10$ as the initial value and assume $\eta=0.2$. Using gradient descent to iterate $x$ for 10 times we can see that, eventually, the value of $x$ approaches the optimal solution.

The progress of optimizing over $x$ can be plotted as follows.

#### Learning Rate

The learning rate $\eta$ can be set by the algorithm designer. If we use a learning rate that is too small, it will cause $x$ to update very slowly, requiring more iterations to get a better solution. To show what happens in such a case, consider the progress in the same optimization problem for $\eta = 0.05$. As we can see, even after 10 steps we are still very far from the optimal solution.

Conversely, if we use an excessively high learning rate, $\left|\eta f'(x)\right|$ might be too large for the first-order Taylor expansion formula. That is, the term $\mathcal{O}(\eta^2 f'^2(x))$ in  might become significant. In this case, we cannot guarantee that the iteration of $x$ will be able to lower the value of $f(x)$. For example, when we set the learning rate to $\eta=1.1$, $x$ overshoots the optimal solution $x=0$ and gradually diverges.

#### Local Minima

To illustrate what happens for nonconvex functions consider the case of $f(x) = x \cdot \cos(cx)$ for some constant $c$. This function has infinitely many local minima. Depending on our choice of the learning rate and depending on how well conditioned the problem is, we may end up with one of many solutions. The example below illustrates how an (unrealistically) high learning rate will lead to a poor local minimum.

### Multivariate Gradient Descent

Now that we have a better intuition of the univariate case, let's consider the situation where $\mathbf{x} = [x_1, x_2, \ldots, x_d]^\top$. That is, the objective function $f: \mathbb{R}^d \to \mathbb{R}$ maps vectors into scalars. Correspondingly its gradient is multivariate, too. It is a vector consisting of $d$ partial derivatives:

In other words, up to second-order terms in $\boldsymbol{\epsilon}$ the direction of steepest descent is given by the negative gradient $-\nabla f(\mathbf{x})$. Choosing a suitable learning rate $\eta > 0$ yields the prototypical gradient descent algorithm:

To avoid cumbersome notation we define $\mathbf{H} \stackrel{\textrm{def}}{=} \nabla^2 f(\mathbf{x})$ to be the Hessian of $f$, which is a $d \times d$ matrix. For small $d$ and simple problems $\mathbf{H}$ is easy to compute. For deep neural networks, on the other hand, $\mathbf{H}$ may be prohibitively large, due to the cost of storing $\mathcal{O}(d^2)$ entries. Furthermore it may be too expensive to compute via backpropagation. For now let's ignore such considerations and look at what algorithm we would get.

After all, the minimum of $f$ satisfies $\nabla f = 0$.
Following calculus rules in ,
by taking derivatives of  with regard to $\boldsymbol{\epsilon}$ and ignoring higher-order terms we arrive at

which holds for some $\xi^{(k)} \in [x^{(k)} - e^{(k)}, x^{(k)}]$. Dividing the above expansion by $f''(x^{(k)})$ yields

Consequently, whenever we are in a region of bounded $\left|f'''(\xi^{(k)})\right| / (2f''(x^{(k)})) \leq c$, we have a quadratically decreasing error

While this is not quite as good as the full Newton's method, it is still much better than not using it.
To see why this might be a good idea consider a situation where one variable denotes height in millimeters and the other one denotes height in kilometers. Assuming that for both the natural scale is in meters, we have a terrible mismatch in parametrizations. Fortunately, using preconditioning removes this. Effectively preconditioning with gradient descent amounts to selecting a different learning rate for each variable (coordinate of vector $\mathbf{x}$).
As we will see later, preconditioning drives some of the innovation in stochastic gradient descent optimization algorithms.

#### Gradient Descent with Line Search

One of the key problems in gradient descent is that we might overshoot the goal or make insufficient progress. A simple fix for the problem is to use line search in conjunction with gradient descent. That is, we use the direction given by $\nabla f(\mathbf{x})$ and then perform binary search as to which learning rate $\eta$ minimizes $f(\mathbf{x} - \eta \nabla f(\mathbf{x}))$.

This algorithm converges rapidly (for an analysis and proof see e.g., ). However, for the purpose of deep learning this is not quite so feasible, since each step of the line search would require us to evaluate the objective function on the entire dataset. This is way too costly to accomplish.

### Summary

* Learning rates matter. Too large and we diverge, too small and we do not make progress.
* Gradient descent can get stuck in local minima.
* In high dimensions adjusting the learning rate is complicated.
* Preconditioning can help with scale adjustment.
* Newton's method is a lot faster once it has started working properly in convex problems.
* Beware of using Newton's method without any adjustments for nonconvex problems.

### Exercises

1. Experiment with different learning rates and objective functions for gradient descent.
1. Implement line search to minimize a convex function in the interval $[a, b]$.
    1. Do you need derivatives for binary search, i.e., to decide whether to pick $[a, (a+b)/2]$ or $[(a+b)/2, b]$.
    1. How rapid is the rate of convergence for the algorithm?
    1. Implement the algorithm and apply it to minimizing $\log (\exp(x) + \exp(-2x -3))$.
1. Design an objective function defined on $\mathbb{R}^2$ where gradient descent is exceedingly slow. Hint: scale different coordinates differently.
1. Implement the lightweight version of Newton's method using preconditioning:
    1. Use diagonal Hessian as preconditioner.
    1. Use the absolute values of that rather than the actual (possibly signed) values.
    1. Apply this to the problem above.
1. Apply the algorithm above to a number of objective functions (convex or not). What happens if you rotate coordinates by $45$ degrees?

[Discussions](https://discuss.d2l.ai/t/351)

## Stochastic Gradient Descent

In earlier chapters we kept using stochastic gradient descent in our training procedure, however, without explaining why it works.
To shed some light on it,
we just described the basic principles of gradient descent
in .
In this section, we go on to discuss
*stochastic gradient descent* in greater detail.

### Stochastic Gradient Updates

In deep learning, the objective function is usually the average of the loss functions for each example in the training dataset.
Given a training dataset of $n$ examples,
we assume that $f_i(\mathbf{x})$ is the loss function
with respect to the training example of index $i$,
where $\mathbf{x}$ is the parameter vector.
Then we arrive at the objective function

If gradient descent is used, the computational cost for each independent variable iteration is $\mathcal{O}(n)$, which grows linearly with $n$. Therefore, when the  training dataset is larger, the cost of gradient descent for each iteration will be higher.

Stochastic gradient descent (SGD) reduces computational cost at each iteration. At each iteration of stochastic gradient descent, we uniformly sample an index $i\in\{1,\ldots, n\}$ for data examples at random, and compute the gradient $\nabla f_i(\mathbf{x})$ to update $\mathbf{x}$:

This means that, on average, the stochastic gradient is a good estimate of the gradient.

Now, we will compare it with gradient descent by adding random noise with a mean of 0 and a variance of 1 to the gradient to simulate a stochastic gradient descent.

As we can see, the trajectory of the variables in the stochastic gradient descent is much more noisy than the one we observed in gradient descent in . This is due to the stochastic nature of the gradient. That is, even when we arrive near the minimum, we are still subject to the uncertainty injected by the instantaneous gradient via $\eta \nabla f_i(\mathbf{x})$. Even after 50 steps the quality is still not so good. Even worse, it will not improve after additional steps (we encourage you to experiment with a larger number of steps to confirm this). This leaves us with the only alternative: change the learning rate $\eta$. However, if we pick this too small, we will not make any meaningful progress initially. On the other hand, if we pick it too large, we will not get a good solution, as seen above. The only way to resolve these conflicting goals is to reduce the learning rate *dynamically* as optimization progresses.

This is also the reason for adding a learning rate function `lr` into the `sgd` step function. In the example above any functionality for learning rate scheduling lies dormant as we set the associated `lr` function to be constant.

### Dynamic Learning Rate

Replacing $\eta$ with a time-dependent learning rate $\eta(t)$ adds to the complexity of controlling convergence of an optimization algorithm. In particular, we need to figure out how rapidly $\eta$ should decay. If it is too quick, we will stop optimizing prematurely. If we decrease it too slowly, we waste too much time on optimization. The following are a few basic strategies that are used in adjusting $\eta$ over time (we will discuss more advanced strategies later):

In the first *piecewise constant* scenario we decrease the learning rate, e.g., whenever progress in optimization stalls. This is a common strategy for training deep networks. Alternatively we could decrease it much more aggressively by an *exponential decay*. Unfortunately this often leads to premature stopping before the algorithm has converged. A popular choice is *polynomial decay* with $\alpha = 0.5$. In the case of convex optimization there are a number of proofs that show that this rate is well behaved.

Let's see what the exponential decay looks like in practice.

As expected, the variance in the parameters is significantly reduced. However, this comes at the expense of failing to converge to the optimal solution $\mathbf{x} = (0, 0)$. Even after 1000 iteration steps are we are still very far away from the optimal solution. Indeed, the algorithm fails to converge at all. On the other hand, if we use a polynomial decay where the learning rate decays with the inverse square root of the number of steps, convergence gets better after only 50 steps.

There exist many more choices for how to set the learning rate. For instance, we could start with a small rate, then rapidly ramp up and then decrease it again, albeit more slowly. We could even alternate between smaller and larger learning rates. There exists a large variety of such schedules. For now let's focus on learning rate schedules for which a comprehensive theoretical analysis is possible, i.e., on learning rates in a convex setting. For general nonconvex problems it is very difficult to obtain meaningful convergence guarantees, since in general minimizing nonlinear nonconvex problems is NP hard. For a survey see e.g., the excellent [lecture notes](https://www.stat.cmu.edu/%7Eryantibs/convexopt-F15/lectures/26-nonconvex.pdf) of Tibshirani 2015.

### Convergence Analysis for Convex Objectives

The following convergence analysis of stochastic gradient descent for convex objective functions
is optional and primarily serves to convey more intuition about the problem.
We limit ourselves to one of the simplest proofs .
Significantly more advanced proof techniques exist, e.g., whenever the objective function is particularly well behaved.

Suppose that the objective function $f(\boldsymbol{\xi}, \mathbf{x})$ is convex in $\mathbf{x}$
for all $\boldsymbol{\xi}$.
More concretely,
we consider the stochastic gradient descent update:

the expected risk and by $R^*$ its minimum with regard to $\mathbf{x}$. Last let $\mathbf{x}^*$ be the minimizer (we assume that it exists within the domain where $\mathbf{x}$ is defined). In this case we can track the distance between the current parameter $\mathbf{x}_t$ at time $t$ and the risk minimizer $\mathbf{x}^*$ and see whether it improves over time:

We are mostly interested in how the distance between $\mathbf{x}_t$ and $\mathbf{x}^*$ changes *in expectation*. In fact, for any specific sequence of steps the distance might well increase, depending on whichever $\boldsymbol{\xi}_t$ we encounter. Hence we need to bound the dot product.
Since for any convex function $f$ it holds that
$f(\mathbf{y}) \geq f(\mathbf{x}) + \langle f'(\mathbf{x}), \mathbf{y} - \mathbf{x} \rangle$
for all $\mathbf{x}$ and $\mathbf{y}$,
by convexity we have

This means that we make progress as long as the  difference between current loss and the optimal loss outweighs $\eta_t L^2/2$. Since this difference is bound to converge to zero it follows that the learning rate $\eta_t$ also needs to *vanish*.

Next we take expectations over . This yields

Note that we exploited that $\mathbf{x}_1$ is given and thus the expectation can be dropped. Last define

by Jensen's inequality (setting $i=t$, $\alpha_i = \eta_t/\sum_{t=1}^T \eta_t$ in ) and convexity of $R$ it follows that $E[R(\mathbf{x}_t)] \geq E[R(\bar{\mathbf{x}})]$, thus

\left[E[\bar{\mathbf{x}}]\right] - R^* \leq \frac{r^2 + L^2 \sum_{t=1}^T \eta_t^2}{2 \sum_{t=1}^T \eta_t},

A similar reasoning shows that the probability of picking some sample (i.e., training example) *exactly once* is given by

## Minibatch Stochastic Gradient Descent

So far we encountered two extremes in the approach to gradient-based learning:  uses the full dataset to compute gradients and to update parameters, one pass at a time. Conversely  processes one training example at a time to make progress.
Either of them has its own drawbacks.
Gradient descent is not particularly *data efficient* whenever data is very similar.
Stochastic gradient descent is not particularly *computationally efficient* since CPUs and GPUs cannot exploit the full power of vectorization.
This suggests that there might be something in between,
and in fact, that is what we have been using so far in the examples we discussed.

### Vectorization and Caches

At the heart of the decision to use minibatches is computational efficiency. This is most easily understood when considering parallelization to multiple GPUs and multiple servers. In this case we need to send at least one image to each GPU. With 8 GPUs per server and 16 servers we already arrive at a minibatch size no smaller than 128.

Things are a bit more subtle when it comes to single GPUs or even CPUs. These devices have multiple types of memory, often multiple types of computational units and different bandwidth constraints between them.
For instance, a CPU has a small number of registers and then the L1, L2, and in some cases even L3 cache (which is shared among different processor cores).
These caches are of increasing size and latency (and at the same time they are of decreasing bandwidth).
Suffice to say, the processor is capable of performing many more operations than what the main memory interface is able to provide.

First, a 2GHz CPU with 16 cores and AVX-512 vectorization can process up to $2 \cdot 10^9 \cdot 16 \cdot 32 = 10^{12}$ bytes per second. The capability of GPUs easily exceeds this number by a factor of 100. On the other hand, a midrange server processor might not have much more than 100 GB/s bandwidth, i.e., less than one tenth of what would be required to keep the processor fed. To make matters worse, not all memory access is created equal: memory interfaces are typically 64 bit wide or wider (e.g., on GPUs up to 384 bit), hence reading a single byte incurs the cost of a much wider access.

Second, there is significant overhead for the first access whereas sequential access is relatively cheap (this is often called a burst read). There are many more things to keep in mind, such as caching when we have multiple sockets, chiplets, and other structures.
See this [Wikipedia article](https://en.wikipedia.org/wiki/Cache_hierarchy)
for a more in-depth discussion.

The way to alleviate these constraints is to use a hierarchy of CPU caches that are actually fast enough to supply the processor with data. This is *the* driving force behind batching in deep learning. To keep matters simple, consider matrix-matrix multiplication, say $\mathbf{A} = \mathbf{B}\mathbf{C}$. We have a number of options for calculating $\mathbf{A}$. For instance, we could try the following:

1. We could compute $\mathbf{A}_{ij} = \mathbf{B}_{i,:} \mathbf{C}_{:,j}$, i.e., we could compute it elementwise by means of dot products.
1. We could compute $\mathbf{A}_{:,j} = \mathbf{B} \mathbf{C}_{:,j}$, i.e., we could compute it one column at a time. Likewise we could compute $\mathbf{A}$ one row $\mathbf{A}_{i,:}$ at a time.
1. We could simply compute $\mathbf{A} = \mathbf{B} \mathbf{C}$.
1. We could break $\mathbf{B}$ and $\mathbf{C}$ into smaller block matrices and compute $\mathbf{A}$ one block at a time.

If we follow the first option, we will need to copy one row and one column vector into the CPU each time we want to compute an element $\mathbf{A}_{ij}$. Even worse, due to the fact that matrix elements are aligned sequentially we are thus required to access many disjoint locations for one of the two vectors as we read them from memory. The second option is much more favorable. In it, we are able to keep the column vector $\mathbf{C}_{:,j}$ in the CPU cache while we keep on traversing through $\mathbf{B}$. This halves the memory bandwidth requirement with correspondingly faster access. Of course, option 3 is most desirable. Unfortunately, most matrices might not entirely fit into cache (this is what we are discussing after all). However, option 4 offers a practically useful alternative: we can move blocks of the matrix into cache and multiply them locally. Optimized libraries take care of this for us. Let's have a look at how efficient these operations are in practice.

Beyond computational efficiency, the overhead introduced by Python and by the deep learning framework itself is considerable. Recall that each time we execute a command the Python interpreter sends a command to the MXNet engine which needs to insert it into the computational graph and deal with it during scheduling. Such overhead can be quite detrimental. In short, it is highly advisable to use vectorization (and matrices) whenever possible.

Since we will benchmark the running time frequently in the rest of the book, let's define a timer.

Element-wise assignment simply iterates over all rows and columns of $\mathbf{B}$ and $\mathbf{C}$ respectively to assign the value to $\mathbf{A}$.

A faster strategy is to perform column-wise assignment.

Last, the most effective manner is to perform the entire operation in one block.
Note that multiplying any two matrices $\mathbf{B} \in \mathbb{R}^{m \times n}$ and $\mathbf{C} \in \mathbb{R}^{n \times p}$ takes approximately $2mnp$ floating point operations,
when scalar multiplication and addition are counted as separate operations (fused in practice).
Thus, multiplying two $256 \times 256$ matrices
takes $0.03$ billion floating point operations.
Let's see what the respective speed of the operations is.

### Minibatches

In the past we took it for granted that we would read *minibatches* of data rather than single observations to update parameters. We now give a brief justification for it. Processing single observations requires us to perform many single matrix-vector (or even vector-vector) multiplications, which is quite expensive and which incurs a significant overhead on behalf of the underlying deep learning framework. This applies both to evaluating a network when applied to data (often referred to as inference) and when computing gradients to update parameters. That is, this applies whenever we perform $\mathbf{w} \leftarrow \mathbf{w} - \eta_t \mathbf{g}_t$ where

Let's see what this does to the statistical properties of $\mathbf{g}_t$: since both $\mathbf{x}_t$ and also all elements of the minibatch $\mathcal{B}_t$ are drawn uniformly at random from the training set, the expectation of the gradient remains unchanged. The variance, on the other hand, is reduced significantly. Since the minibatch gradient is composed of $b \stackrel{\textrm{def}}{=} |\mathcal{B}_t|$ independent gradients which are being averaged, its standard deviation is reduced by a factor of $b^{-\frac{1}{2}}$. This, by itself, is a good thing, since it means that the updates are more reliably aligned with the full gradient.

Naively this would indicate that choosing a large minibatch $\mathcal{B}_t$ would be universally desirable. Alas, after some point, the additional reduction in standard deviation is minimal when compared to the linear increase in computational cost. In practice we pick a minibatch that is large enough to offer good computational efficiency while still fitting into the memory of a GPU. To illustrate the savings let's have a look at some code. In it we perform the same matrix-matrix multiplication, but this time broken up into "minibatches" of 64 columns at a time.

As we can see, the computation on the minibatch is essentially as efficient as on the full matrix. A word of caution is in order. In  we used a type of regularization that was heavily dependent on the amount of variance in a minibatch. As we increase the latter, the variance decreases and with it the benefit of the noise-injection due to batch normalization. See e.g.,  for details on how to rescale and compute the appropriate terms.

### Reading the Dataset

Let's have a look at how minibatches are efficiently generated from data. In the following we use a dataset developed by NASA to test the wing [noise from different aircraft](https://archive.ics.uci.edu/dataset/291/airfoil+self+noise) to compare these optimization algorithms. For convenience we only use the first $1,500$ examples. The data is whitened for preprocessing, i.e., we remove the mean and rescale the variance to $1$ per coordinate.

### Implementation from Scratch

Recall the minibatch stochastic gradient descent implementation from . In the following we provide a slightly more general implementation. For convenience it has the same call signature as the other optimization algorithms introduced later in this chapter. Specifically, we add the status
input `states` and place the hyperparameter in dictionary `hyperparams`. In
addition, we will average the loss of each minibatch example in the training
function, so the gradient in the optimization algorithm does not need to be
divided by the batch size.

Next, we implement a generic training function to facilitate the use of the other optimization algorithms introduced later in this chapter. It initializes a linear regression model and can be used to train the model with minibatch stochastic gradient descent and other algorithms introduced subsequently.

Let's see how optimization proceeds for batch gradient descent. This can be achieved by setting the minibatch size to 1500 (i.e., to the total number of examples). As a result the model parameters are updated only once per epoch. There is little progress. In fact, after 6 steps progress stalls.

When the batch size equals 1, we use stochastic gradient descent for optimization. For simplicity of implementation we picked a constant (albeit small) learning rate. In stochastic gradient descent, the model parameters are updated whenever an example is processed. In our case this amounts to 1500 updates per epoch. As we can see, the decline in the value of the objective function slows down after one epoch. Although both the procedures processed 1500 examples within one epoch, stochastic gradient descent consumes more time than gradient descent in our experiment. This is because stochastic gradient descent updated the parameters more frequently and since it is less efficient to process single observations one at a time.

Finally, when the batch size equals 100, we use minibatch stochastic gradient descent for optimization. The time required per epoch is shorter than the time needed for stochastic gradient descent and the time for batch gradient descent.

Reducing the batch size to 10, the time for each epoch increases because the workload for each batch is less efficient to execute.

Now we can compare the time vs. loss for the previous four experiments. As can be seen, although stochastic gradient descent converges faster than GD in terms of number of examples processed, it uses more time to reach the same loss than GD because computing the gradient example by example is not as efficient. Minibatch stochastic gradient descent is able to trade-off convergence speed and computation efficiency. A minibatch size of 10 is more efficient than stochastic gradient descent; a minibatch size of 100 even outperforms GD in terms of runtime.

### Concise Implementation

In Gluon, we can use the `Trainer` class to call optimization algorithms. This is used to implement a generic training function. We will use this throughout the current chapter.

Using Gluon to repeat the last experiment shows identical behavior.

### Summary

* Vectorization makes code more efficient due to reduced overhead arising from the deep learning framework and due to better memory locality and caching on CPUs and GPUs.
* There is a trade-off between statistical efficiency arising from stochastic gradient descent and computational efficiency arising from processing large batches of data at a time.
* Minibatch stochastic gradient descent offers the best of both worlds: computational and statistical efficiency.
* In minibatch stochastic gradient descent we process batches of data obtained by a random permutation of the training data (i.e., each observation is processed only once per epoch, albeit in random order).
* It is advisable to decay the learning rates during training.
* In general, minibatch stochastic gradient descent is faster than stochastic gradient descent and gradient descent for convergence to a smaller risk, when measured in terms of clock time.

### Exercises

1. Modify the batch size and learning rate and observe the rate of decline for the value of the objective function and the time consumed in each epoch.
1. Read the MXNet documentation and use the `Trainer` class `set_learning_rate` function to reduce the learning rate of the minibatch stochastic gradient descent to 1/10 of its previous value after each epoch.
1. Compare minibatch stochastic gradient descent with a variant that actually *samples with replacement* from the training set. What happens?
1. An evil genie replicates your dataset without telling you (i.e., each observation occurs twice and your dataset grows to twice its original size, but nobody told you). How does the behavior of stochastic gradient descent, minibatch stochastic gradient descent and that of gradient descent change?

[Discussions](https://discuss.d2l.ai/t/353)

[Discussions](https://discuss.d2l.ai/t/1068)

[Discussions](https://discuss.d2l.ai/t/1069)

## Momentum

In  we reviewed what happens when performing stochastic gradient descent, i.e., when performing optimization where only a noisy variant of the gradient is available. In particular, we noticed that for noisy gradients we need to be extra cautious when it comes to choosing the learning rate in the face of noise. If we decrease it too rapidly, convergence stalls. If we are too lenient, we fail to converge to a good enough solution since noise keeps on driving us away from optimality.

### Basics

In this section, we will explore more effective optimization algorithms, especially for certain types of optimization problems that are common in practice.

#### Leaky Averages

The previous section saw us discussing minibatch SGD as a means for accelerating computation. It also had the nice side-effect that averaging gradients reduced the amount of variance. The minibatch stochastic gradient descent can be calculated by:

To keep the notation simple, here we used $\mathbf{h}_{i, t-1} = \partial_{\mathbf{w}} f(\mathbf{x}_i, \mathbf{w}_{t-1})$ as the stochastic gradient descent for sample $i$ using the weights updated at time $t-1$.
It would be nice if we could benefit from the effect of variance reduction even beyond averaging gradients on a minibatch. One option to accomplish this task is to replace the gradient computation by a "leaky average":

\mathbf{v}_t = \beta^2 \mathbf{v}_{t-2} + \beta \mathbf{g}_{t-1, t-2} + \mathbf{g}_{t, t-1}
= \ldots, = \sum_{\tau = 0}^{t-1} \beta^{\tau} \mathbf{g}_{t-\tau, t-\tau-1}.
\end{aligned}$$

Large $\beta$ amounts to a long-range average, whereas small $\beta$ amounts to only a slight correction relative to a gradient method. The new gradient replacement no longer points into the direction of steepest descent on a particular instance any longer but rather in the direction of a weighted average of past gradients. This allows us to realize most of the benefits of averaging over a batch without the cost of actually computing the gradients on it. We will revisit this averaging procedure in more detail later.

The above reasoning formed the basis for what is now known as *accelerated* gradient methods, such as gradients with momentum. They enjoy the additional benefit of being much more effective in cases where the optimization problem is ill-conditioned (i.e., where there are some directions where progress is much slower than in others, resembling a narrow canyon). Furthermore, they allow us to average over subsequent gradients to obtain more stable directions of descent. Indeed, the aspect of acceleration even for noise-free convex problems is one of the key reasons why momentum works and why it works so well.

As one would expect, due to its efficacy momentum is a well-studied subject in optimization for deep learning and beyond. See e.g., the beautiful [expository article](https://distill.pub/2017/momentum/) by  for an in-depth analysis and interactive animation. It was proposed by .  has a detailed theoretical discussion in the context of convex optimization. Momentum in deep learning has been known to be beneficial for a long time. See e.g., the discussion by  for details.

#### An Ill-conditioned Problem

To get a better understanding of the geometric properties of the momentum method we revisit gradient descent, albeit with a significantly less pleasant objective function. Recall that in  we used $f(\mathbf{x}) = x_1^2 + 2 x_2^2$, i.e., a moderately distorted ellipsoid objective. We distort this function further by stretching it out in the $x_1$ direction via

\begin{aligned}
\mathbf{v}_t &\leftarrow \beta \mathbf{v}_{t-1} + \mathbf{g}_{t, t-1}, \\
\mathbf{x}_t &\leftarrow \mathbf{x}_{t-1} - \eta_t \mathbf{v}_t.
\end{aligned}

This is a general quadratic function. For positive definite matrices $\mathbf{Q} \succ 0$, i.e., for matrices with positive eigenvalues this has a minimizer at $\mathbf{x}^* = -\mathbf{Q}^{-1} \mathbf{c}$ with minimum value $b - \frac{1}{2} \mathbf{c}^\top \mathbf{Q}^{-1} \mathbf{c}$. Hence we can rewrite $h$ as

Here $b' = b - \frac{1}{2} \mathbf{c}^\top \mathbf{Q}^{-1} \mathbf{c}$. Since $\mathbf{O}$ is only an orthogonal matrix this does not perturb the gradients in a meaningful way. Expressed in terms of $\mathbf{z}$ gradient descent becomes

\mathbf{v}_t & = \beta \mathbf{v}_{t-1} + \boldsymbol{\Lambda} \mathbf{z}_{t-1} \\
\mathbf{z}_t & = \mathbf{z}_{t-1} - \eta \left(\beta \mathbf{v}_{t-1} + \boldsymbol{\Lambda} \mathbf{z}_{t-1}\right) \\
    & = (\mathbf{I} - \eta \boldsymbol{\Lambda}) \mathbf{z}_{t-1} - \eta \beta \mathbf{v}_{t-1}.
\end{aligned}$$

In doing this we just proved the following theorem: gradient descent with and without momentum for a convex quadratic function decomposes into coordinate-wise optimization in the direction of the eigenvectors of the quadratic matrix.

#### Scalar Functions

Given the above result let's see what happens when we minimize the function $f(x) = \frac{\lambda}{2} x^2$. For gradient descent we have

\begin{bmatrix} v_{t+1} \\ x_{t+1} \end{bmatrix} =
\begin{bmatrix} \beta & \lambda \\ -\eta \beta & (1 - \eta \lambda) \end{bmatrix}
\begin{bmatrix} v_{t} \\ x_{t} \end{bmatrix} = \mathbf{R}(\beta, \eta, \lambda) \begin{bmatrix} v_{t} \\ x_{t} \end{bmatrix}.

## Adagrad

Let's begin by considering learning problems with features that occur infrequently.

### Sparse Features and Learning Rates

Imagine that we are training a language model. To get good accuracy we typically want to decrease the learning rate as we keep on training, usually at a rate of $\mathcal{O}(t^{-\frac{1}{2}})$ or slower. Now consider a model training on sparse features, i.e., features that occur only infrequently. This is common for natural language, e.g., it is a lot less likely that we will see the word *preconditioning* than *learning*. However, it is also common in other areas such as computational advertising and personalized collaborative filtering. After all, there are many things that are of interest only for a small number of people.

Parameters associated with infrequent features only receive meaningful updates whenever these features occur. Given a decreasing learning rate we might end up in a situation where the parameters for common features converge rather quickly to their optimal values, whereas for infrequent features we are still short of observing them sufficiently frequently before their optimal values can be determined. In other words, the learning rate either decreases too slowly for frequent features or too quickly for infrequent ones.

A possible hack to redress this issue would be to count the number of times we see a particular feature and to use this as a clock for adjusting learning rates. That is, rather than choosing a learning rate of the form $\eta = \frac{\eta_0}{\sqrt{t + c}}$ we could use $\eta_i = \frac{\eta_0}{\sqrt{s(i, t) + c}}$. Here $s(i, t)$ counts the number of nonzeros for feature $i$ that we have observed up to time $t$. This is actually quite easy to implement at no meaningful overhead. However, it fails whenever we do not quite have sparsity but rather just data where the gradients are often very small and only rarely large. After all, it is unclear where one would draw the line between something that qualifies as an observed feature or not.

Adagrad by  addresses this by replacing the rather crude counter $s(i, t)$ by an aggregate of the squares of previously observed gradients. In particular, it uses $s(i, t+1) = s(i, t) + \left(\partial_i f(\mathbf{x})\right)^2$ as a means to adjust the learning rate. This has two benefits: first, we no longer need to decide just when a gradient is large enough. Second, it scales automatically with the magnitude of the gradients. Coordinates that routinely correspond to large gradients are scaled down significantly, whereas others with small gradients receive a much more gentle treatment. In practice this leads to a very effective optimization procedure for computational advertising and related problems. But this hides some of the additional benefits inherent in Adagrad that are best understood in the context of preconditioning.

### Preconditioning

Convex optimization problems are good for analyzing the characteristics of algorithms. After all, for most nonconvex problems it is difficult to derive meaningful theoretical guarantees, but *intuition* and *insight* often carry over.  Let's look at the problem of minimizing $f(\mathbf{x}) = \frac{1}{2} \mathbf{x}^\top \mathbf{Q} \mathbf{x} + \mathbf{c}^\top \mathbf{x} + b$.

As we saw in , it is possible to rewrite this problem in terms of its eigendecomposition $\mathbf{Q} = \mathbf{U}^\top \boldsymbol{\Lambda} \mathbf{U}$ to arrive at a much simplified problem where each coordinate can be solved individually:

If the condition number $\kappa$ is large, it is difficult to solve the optimization problem accurately. We need to ensure that we are careful in getting a large dynamic range of values right. Our analysis leads to an obvious, albeit somewhat naive question: couldn't we simply "fix" the problem by distorting the space such that all eigenvalues are $1$. In theory this is quite easy: we only need the eigenvalues and eigenvectors of $\mathbf{Q}$ to rescale the problem from $\mathbf{x}$ to one in $\mathbf{z} \stackrel{\textrm{def}}{=} \boldsymbol{\Lambda}^{\frac{1}{2}} \mathbf{U} \mathbf{x}$. In the new coordinate system $\mathbf{x}^\top \mathbf{Q} \mathbf{x}$ could be simplified to $\|\mathbf{z}\|^2$. Alas, this is a rather impractical suggestion. Computing eigenvalues and eigenvectors is in general *much more* expensive than solving the actual  problem.

While computing eigenvalues exactly might be expensive, guessing them and computing them even somewhat approximately may already be a lot better than not doing anything at all. In particular, we could use the diagonal entries of $\mathbf{Q}$ and rescale it accordingly. This is *much* cheaper than computing eigenvalues.

where $\bar{\mathbf{x}}_0$ is the minimizer of $\bar{f}$. Hence the magnitude of the gradient depends both on $\boldsymbol{\Lambda}$ and the distance from optimality. If $\bar{\mathbf{x}} - \bar{\mathbf{x}}_0$ did not change, this would be all that is needed. After all, in this case the magnitude of the gradient $\partial_{\bar{\mathbf{x}}} \bar{f}(\bar{\mathbf{x}})$ suffices. Since AdaGrad is a stochastic gradient descent algorithm, we will see gradients with nonzero variance even at optimality. As a result we can safely use the variance of the gradients as a cheap proxy for the scale of the Hessian. A thorough analysis is beyond the scope of this section (it would be several pages). We refer the reader to  for details.

### The Algorithm

Let's formalize the discussion from above. We use the variable $\mathbf{s}_t$ to accumulate past gradient variance as follows.

We are going to implement Adagrad using the same learning rate previously, i.e., $\eta = 0.4$. As we can see, the iterative trajectory of the independent variable is smoother. However, due to the cumulative effect of $\boldsymbol{s}_t$, the learning rate continuously decays, so the independent variable does not move as much during later stages of iteration.

As we increase the learning rate to $2$ we see much better behavior. This already indicates that the decrease in learning rate might be rather aggressive, even in the noise-free case and we need to ensure that parameters converge appropriately.

### Implementation from Scratch

Just like the momentum method, Adagrad needs to maintain a state variable of the same shape as the parameters.

Compared to the experiment in  we use a
larger learning rate to train the model.

### Concise Implementation

Using the `Trainer` instance of the algorithm `adagrad`, we can invoke the Adagrad algorithm in Gluon.

### Summary

* Adagrad decreases the learning rate dynamically on a per-coordinate basis.
* It uses the magnitude of the gradient as a means of adjusting how quickly progress is achieved - coordinates with large gradients are compensated with a smaller learning rate.
* Computing the exact second derivative is typically infeasible in deep learning problems due to memory and computational constraints. The gradient can be a useful proxy.
* If the optimization problem has a rather uneven structure Adagrad can help mitigate the distortion.
* Adagrad is particularly effective for sparse features where the learning rate needs to decrease more slowly for infrequently occurring terms.
* On deep learning problems Adagrad can sometimes be too aggressive in reducing learning rates. We will discuss strategies for mitigating this in the context of .

### Exercises

1. Prove that for an orthogonal matrix $\mathbf{U}$ and a vector $\mathbf{c}$ the following holds: $\|\mathbf{c} - \mathbf{\delta}\|_2 = \|\mathbf{U} \mathbf{c} - \mathbf{U} \mathbf{\delta}\|_2$. Why does this mean that the magnitude of perturbations does not change after an orthogonal change of variables?
1. Try out Adagrad for $f(\mathbf{x}) = 0.1 x_1^2 + 2 x_2^2$ and also for the objective function was rotated by 45 degrees, i.e., $f(\mathbf{x}) = 0.1 (x_1 + x_2)^2 + 2 (x_1 - x_2)^2$. Does it behave differently?
1. Prove [Gerschgorin's circle theorem](https://en.wikipedia.org/wiki/Gershgorin_circle_theorem) which states that eigenvalues $\lambda_i$ of a matrix $\mathbf{M}$ satisfy $|\lambda_i - \mathbf{M}_{jj}| \leq \sum_{k \neq j} |\mathbf{M}_{jk}|$ for at least one choice of $j$.
1. What does Gerschgorin's theorem tell us about the eigenvalues of the diagonally preconditioned matrix $\textrm{diag}^{-\frac{1}{2}}(\mathbf{M}) \mathbf{M} \textrm{diag}^{-\frac{1}{2}}(\mathbf{M})$?
1. Try out Adagrad for a proper deep network, such as  when applied to Fashion-MNIST.
1. How would you need to modify Adagrad to achieve a less aggressive decay in learning rate?

[Discussions](https://discuss.d2l.ai/t/355)

[Discussions](https://discuss.d2l.ai/t/1072)

[Discussions](https://discuss.d2l.ai/t/1073)

## RMSProp

One of the key issues in  is that the learning rate decreases at a predefined schedule of effectively $\mathcal{O}(t^{-\frac{1}{2}})$. While this is generally appropriate for convex problems, it might not be ideal for nonconvex ones, such as those encountered in deep learning. Yet, the coordinate-wise adaptivity of Adagrad is highly desirable as a preconditioner.

One way of fixing this problem would be to use $\mathbf{s}_t / t$. For reasonable distributions of $\mathbf{g}_t$ this will converge. Unfortunately it might take a very long time until the limit behavior starts to matter since the procedure remembers the full trajectory of values. An alternative is to use a leaky average in the same way we used in the momentum method, i.e., $\mathbf{s}_t \leftarrow \gamma \mathbf{s}_{t-1} + (1-\gamma) \mathbf{g}_t^2$ for some parameter $\gamma > 0$. Keeping all other parts unchanged yields RMSProp.

### The Algorithm

Let's write out the equations in detail.

\begin{aligned}
\mathbf{s}_t & = (1 - \gamma) \mathbf{g}_t^2 + \gamma \mathbf{s}_{t-1} \\
& = (1 - \gamma) \left(\mathbf{g}_t^2 + \gamma \mathbf{g}_{t-1}^2 + \gamma^2 \mathbf{g}_{t-2} + \ldots, \right).
\end{aligned}

## Adam

In the discussions leading up to this section we encountered a number of techniques for efficient optimization. Let's recap them in detail here:

* We saw that  is more effective than Gradient Descent when solving optimization problems, e.g., due to its inherent resilience to redundant data.
* We saw that  affords significant additional efficiency arising from vectorization, using larger sets of observations in one minibatch. This is the key to efficient multi-machine, multi-GPU and overall parallel processing.
*  added a mechanism for aggregating a history of past gradients to accelerate convergence.
*  used per-coordinate scaling to allow for a computationally efficient preconditioner.
*  decoupled per-coordinate scaling from a learning rate adjustment.

Adam  combines all these techniques into one efficient learning algorithm. As expected, this is an algorithm that has become rather popular as one of the more robust and effective optimization algorithms to use in deep learning. It is not without issues, though. In particular,  show that there are situations where Adam can diverge due to poor variance control. In a follow-up work  proposed a hotfix to Adam, called Yogi which addresses these issues. More on this later. For now let's review the Adam algorithm.

### The Algorithm

One of the key components of Adam is that it uses exponential weighted moving averages (also known as leaky averaging) to obtain an estimate of both the momentum and also the second moment of the gradient. That is, it uses the state variables

Armed with the proper estimates we can now write out the update equations. First, we rescale the gradient in a manner very much akin to that of RMSProp to obtain

Reviewing the design of Adam its inspiration is clear. Momentum and scale are clearly visible in the state variables. Their rather peculiar definition forces us to debias terms (this could be fixed by a slightly different initialization and update condition). Second, the combination of both terms is pretty straightforward, given RMSProp. Last, the explicit learning rate $\eta$ allows us to control the step length to address issues of convergence.

### Implementation

Implementing Adam from scratch is not very daunting. For convenience we store the time step counter $t$ in the `hyperparams` dictionary. Beyond that all is straightforward.

We are ready to use Adam to train the model. We use a learning rate of $\eta = 0.01$.

A more concise implementation is straightforward since `adam` is one of the algorithms provided as part of the Gluon `trainer` optimization library. Hence we only need to pass configuration parameters for an implementation in Gluon.

### Yogi

One of the problems of Adam is that it can fail to converge even in convex settings when the second moment estimate in $\mathbf{s}_t$ blows up. As a fix  proposed a refined update (and initialization) for $\mathbf{s}_t$. To understand what's going on, let's rewrite the Adam update as follows:

The authors furthermore advise to initialize the momentum on a larger initial batch rather than just initial pointwise estimate. We omit the details since they are not material to the discussion and since even without this convergence remains pretty good.

### Summary

* Adam combines features of many optimization algorithms into a fairly robust update rule.
* Created on the basis of RMSProp, Adam also uses EWMA on the minibatch stochastic gradient.
* Adam uses bias correction to adjust for a slow startup when estimating momentum and a second moment.
* For gradients with significant variance we may encounter issues with convergence. They can be amended by using larger minibatches or by switching to an improved estimate for $\mathbf{s}_t$. Yogi offers such an alternative.

### Exercises

1. Adjust the learning rate and observe and analyze the experimental results.
1. Can you rewrite momentum and second moment updates such that it does not require bias correction?
1. Why do you need to reduce the learning rate $\eta$ as we converge?
1. Try to construct a case for which Adam diverges and Yogi converges?

[Discussions](https://discuss.d2l.ai/t/358)

[Discussions](https://discuss.d2l.ai/t/1078)

[Discussions](https://discuss.d2l.ai/t/1079)
