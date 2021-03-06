from django.utils import timezone
from apps.profiles.models import Profile, Post
from apps.tags.models import Tag
from libs.pullBlog import pullBlog, pullBlogFilter
from libs.siteEnums import Gender, Tags, Species, System
from libs.auxHelpers import returnCount
from random import randint, random
import os, re, fnmatch
import data_path
from os.path import join

def makeProfile(speciesType):
    """Creates and returns a new Profile object of provided speciesType.
    
    This will generate first name, last name, gender, age, and location and create
    a new Profile object. If the Profile is of species type 'abandoned' it will be
    populated with the data from a particular recovered blog from the reserves.
    
    If the Profile is of a different (active) species type it will swap positions
    with a pre-existing Profile object, be set to visible = False, given an initial
    energy value and have a Post created in honor of its birth.
    """
    fn, ln, gn = nameGenerate()
    profile = Profile(
        fname = fn,
        lname = ln,
        gender = gn,
        age = ageGenerate(),
        location = locationGenerate(),
        species = speciesType
    )
    assignImages(profile) #contains a profile.save()
    if speciesType == Species.abandoned:
        profile.blog_id, profile.blog_url, profile.last_login = makePosts(profile)
        profile.position = profile.id
        profile.save()
    else:
        swapPosition(profile, Profile.objects.all().order_by('?')[0])
        profile.last_login = timezone.now()
        profile.visible = False
        profile.energy = System.energy
        profile.save()
        makeBirthPost(profile)
    return profile

def makeBuildAbandoned(blogNo):
    """Function specifically for fully populating the database from all recovered blogs."""
    blogId, url, lastUpdate, posts = pullBlogFilter(blogNo)
    if blogId:
        fn, ln, gn = nameGenerate()
        profile = Profile(
            fname = fn,
            lname = ln,
            gender = gn,
            age = ageGenerate(),
            location = locationGenerate(),
            species = Species.abandoned,
            blog_id = blogId,
            blog_url = url,
            last_login = lastUpdate
        )
        profile.position = profile.id
        assignImages(profile)
        for post in posts:
            newPost = Post(
                post_profile=profile,
                date_published=post[1],
                post_content=re.sub('<[^<]+?>', '', post[2])
            )
            newPost.save()
        return profile
    return None

def makeAnonymous():
    """Creates and returns a new Profile object of species type visitor.
    
    The first and last names of the anonymous visitor are pre-supplied. As it
    is of an active species type it will swap positions with a pre-existing Profile
    and receive a post in honor of its birth.
    """
    profile = Profile(
        fname = 'Anonymous',
        lname = 'Visitor',
        gender = randint(0, 1),
        age = ageGenerate(),
        location = locationGenerate(),
        species = Species.visitor,
        visible = False,
        last_login = timezone.now()
    )
    assignImages(profile) #contains a profile.save()
    swapPosition(profile, Profile.objects.all().order_by('?')[0])
    makeBirthPost(profile)
    return profile

def makeFriends(profile):
    """Assigns a number of friends to supplied Profile object. Returns nothing."""
    minFriends = System.minFriends
    maxFriends = System.maxFriends
    manyFriends = randint(minFriends, maxFriends)
    if profile.friends.count() < manyFriends:
        newfriends = Profile.objects.exclude(id=profile.id).filter(species=Species.abandoned).order_by('?')[:manyFriends]
        for friend in newfriends:
            if profile.friends.count() > manyFriends:
                break
            if friend.friends.count() < manyFriends:
                profile.friends.add(friend)
    profile.save()

def makePosts(profile):
    """Creates Post objects from posts of a recovered blog from source data.
    
    Returns a blog id, url, and last updated. Requires Profile to assign created Posts.
    """
    blogId, url, lastUpdate, posts = pullBlog(None)
    for post in posts:
        newPost = Post(
            post_profile=profile,
            date_published=post[1],
            post_content=re.sub('<[^<]+?>', '', post[2])
        )
        newPost.save()
    return blogId, url, lastUpdate

def makeUserPost(request, content, tagname):
    """Creates and returns a new Post object for the session profile.
    
    Takes as input request object, post content, and a tag id
    """
    profile = Profile.objects.get(id=request.session['session_id'])
    newPost = makeTaggedPost(profile, content, tagname)
    newPost.just_posted = True
    newPost.save()
    return newPost

def makeTaggedPost(profile, content, tagname):
    """Creates and returns a new Post object assigned to supplied Profile.
    
    Takes as input a Profile object, a content string, and an id for a Tag object.
    """
    newPost = Post(
        post_content=content,
        post_profile=profile,
        date_published=timezone.now()
    )
    newPost.save()
    newPost.tags.add(Tag.objects.filter(name=tagname)[0])
    newPost.save()
    return newPost

def makeBirthPost(profile):
    """Creates a Post announcing the birth of a Profile into the wilderness. Returns nothing."""
    postOut = profile.fullName + ' entered the openspace wilderness.'
    makeTaggedPost(profile, postOut, 'birth')

def makeDeathPost(profile):
    """Creates a Post announcing the death of a Profile in the wilderness. Returns nothing."""
    postOut = profile.fullName + ' died of starvation'
    makeTaggedPost(profile, postOut, 'death')

def eatPrey(predator, prey):
    """Predator type Profile consumes the energy of a Prey type Profile. Returns True if success.
    
    The prey's energy is added to the predators. The prey will die
    and Posts are created for both predator and prey.
    """
    if predator.isFull:
        predator.energy += 2
        predator.save()
        return False
    newEnergy = prey.energy
    predator.energy += newEnergy
    predator.meals += 1
    predator.save()
    prey.die()
    postOut = 'eaten by ' + predator.fullName
    makeTaggedPost(prey, postOut, 'predation')
    postOut = 'gained ' + str(newEnergy) + 'from eating ' + prey.fullName
    makeTaggedPost(predator, postOut, 'predation')
    return True

def grazePost(forager, post):
    """Forager type Profile consumes a portion of the content
    from a selected Post object for energy. Returns True if success.
    
    A bite size is calculated based on modifiers referencing current forager
    type population and a bite is taken from the supplied Post object.
    This bite is added to the forager's profile in the form of a grazePost and the
    grazed section on the target post is replaced with chompChars.
    Energy is equivalent to bite size. 
    """
    if forager.isFull:
        forager.energy += 2
        forager.save()
        return False
    chompChar = ' / '
    start = randint(1, len(post.post_content) - 1)
    if len(post.post_content) < 2:
        return False
    bitesize = randint(System.minBite, System.maxBite) 
    end = randint(start, start+bitesize)
    if end > len(post.post_content):
        end = len(post.post_content)
    if end <= start:
        return False
    bite = post.post_content[start:end]
    bite = bite.replace(chompChar, '')
    if len(bite) > 0:
        grazePost = makeTaggedPost(forager, bite, 'grazing')
        modifier = 0
        foragerCount = Profile.objects.filter(species=Species.forager).count()
        if foragerCount < len(bite):
            modifier = (float(foragerCount) / len(bite)) * 100  #percentage
        nutrients = len(bite) - modifier
        forager.energy += nutrients 
        forager.meals += 1
        forager.save()
        post.post_content = (post.post_content[0:start] +
            (chompChar * (end-start)) + post.post_content[end+1:])
        post.save()
        return True
    return False

def splitTextFile(textFile):
    """Returns a list of strings from a file split at 'newline'."""
    inFile = open(textFile, 'r')
    fileLines = inFile.read().split("\n")
    inFile.close()
    return fileLines

def nameGenerate():
    """Returns a first name, last name, and a gender from data source."""
    femaleNames = splitTextFile(os.path.join(data_path.DATA_PATH,'femaleNames.txt'))
    maleNames = splitTextFile(os.path.join(data_path.DATA_PATH,'maleNames.txt'))
    lastNames = splitTextFile(os.path.join(data_path.DATA_PATH,'lastNames.txt'))
    gender = randint(Gender.female, Gender.male)    
    if gender == Gender.male:
        firstName = firstNameGenerate(maleNames, gender)
        while firstName == '':
            firstName = firstNameGenerate(maleNames, gender)
    else:
        firstName = firstNameGenerate(femaleNames, gender)
        while firstName == '':
            firstName = firstNameGenerate(maleNames, gender)
    return firstName, retrieveName(lastNames), gender

def retrievePopularName(gender):
    """Returns a gendered (male or female) name from 'popularNames.txt.'"""
    names = splitTextFile(os.path.join(data_path.DATA_PATH,'popularNames.txt'))
    x = randint(0, len(names)-1)
    while x % 2 == gender:
        x = randint(0, len(names)-1)
    return names[x]

def retrieveName(names):
    """Returns a random name from a list of names."""
    return names[randint(0, len(names)-1)]

def firstNameGenerate(names, gender):
    """Returns a name. Has a 1 in 4 chance of being a popular name."""
    if randint(0,3) < 3:
        return retrievePopularName(gender)
    return retrieveName(names)

def locationGenerate():
    """Returns a random US city, state location from 'cities.txt'."""
    infile = open(os.path.join(data_path.DATA_PATH,'cities.txt'), 'r')
    data = infile.read()
    infile.close()
    cities = data.split('\n')
    return cities[randint(1, len(cities)-1)]

def ageGenerate():
    """Returns a random age based on a bias."""
    #TRUE AGE SPREAD [25, 35, 45, 18, 55, 11, 65]
    #TRUE AGE BIASES [0.26, 0.25, 0.19, 0.16, 0.06, 0.05, 0.02]
    ages = [11, 18, 25, 35, 45, 55, 65, 90]
    bias = [0.05, 0.25, 0.26, 0.16, 0.19, 0.06, 0.02]
    sel = ageBias(bias)
    age = randint(ages[sel], ages[sel+1])
    return age

def ageBias(weights):
    """Return bias for ageGenerate()."""
    rnd = random() * sum(weights)
    for i, w in enumerate(weights):
        rnd -= w
        if rnd < 0:
            return i

def swapPosition(profileA, profileB):
    """Swaps the position of two supplied Profile objects. Returns nothing."""
    profileA.position, profileB.position = profileB.position, profileA.id
    profileA.save()
    profileB.save()

def assignImages(profile):
    """Selects and assigns a random image number to Profile object based on species type."""
    imgCount = returnCount(profile.speciesReadable)
    profile.img_number = randint(1, imgCount/2)
    profile.save()