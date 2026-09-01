// const
const homeLink = document.getElementById('homeLink');
const photosLink = document.getElementById('photosLink');
const homeSection = document.getElementById('home');
const photoSection = document.getElementById('photos');
const videoContainer = document.getElementById('videoContainer');

// Youtube Video IDs
const PUBLIC_VIDEO_ID = "F2sERCgDESE"; // public video
// const PRIVATE_VIDEO_ID = "zGwszApFEcY" private video, only Obi-Wan


// Load Public Video Test
function loadPublicStream() {
    videoContainer.innerHTML = `
        <iframe 
            src="https://www.youtube.com/embed/${PUBLIC_VIDEO_ID}?autoplay=1&mute=0"
            title="Public Stream"
            frameborder="0" 
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
            allowfullscreen>
        </iframe>
    `;
}


// render 10 photos
function renderTransmittedPhotos() {
    const imageGrid = document.getElementById('imageGrid'); // searches exisiting element in html, assign it variable imageGrid
    // clear container
    imageGrid.innerHTML = '';

    for (let i = 1; i <= 10; i++) {                     // for loop for 10 photo slots
        const img = document.createElement('img');     // creates new element

        img.src = 'images/photo${i}.png';       // sets source file path
        img.alt = 'Transmitted Image ${i}';     // sets alternative text of the image

        imageGrid.appendChild(img);     // places images to page, making it visible
    }
}

// Switch to home view, hiding photo view
homeLink.addEventListener('click', (e)=> {
    e.preventDefault();
    photoSection.classList.add('hidden');
    homeSection.classList.remove('hidden');
});

// Switch to photo view, hiding home view
photosLink.addEventListener('click', (e)=> {
    e.preventDefault();
    homeSection.classList.add('hidden');
    photoSection.classList.remove('hidden');
});

// Loads initiating page
loadPublicStream();
renderTransmittedPhotos();