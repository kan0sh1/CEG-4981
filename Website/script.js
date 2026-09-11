// element refrences
const homeLink = document.getElementById('homeLink');
const photosLink = document.getElementById('photosLink');
const homeSection = document.getElementById('home');
const photoSection = document.getElementById('photos');
const videoContainer = document.getElementById('videoContainer');
const pinInput = document.getElementById('pinInput');
const loginBtn = document.getElementById('loginBtn');
const authStatus = document.getElementById('authStatus');

// Youtube Video IDs
const PUBLIC_VIDEO_ID = "F2sERCgDESE"; // public video


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

// Load Private Video
function loadPrivateStream(video_id) {
    videoContainer.innerHTML = `
    <iframe
        src="https://www.youtube.com/embed/${video_id}?autoplay=1&mute=0"
        title="Private Stream"
        frameborder="0"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
    </iframe>
    `;
}


// render 10 photos
function renderTransmittedPhotos() {
    const imageGrid = document.getElementById('imageGrid'); // searches exisiting element in html
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

// Authentication button click
loginBtn.addEventListener('click', async () => {
    const enteredPin = pinInput.value.trim();    // get entered pin, trim whitespace

    try {   // POST request with PIN to Flask
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ pin: enteredPin })
        });

        const data = await response.json();     // Json response from server

        // if statement, if status is 200 and authenticated
        if (response.ok && data.authenticated) {
            authStatus.textContent = data.message;
            loadPrivateStream(data.video_id); // load private video into iframe
        } else { // else display error message
            authStatus.textContent = data.message || "Authentication failed.";
        }
    } 
    // handles network connection failure or unreachable errors
    catch (error) {
        console.error("Error connecting to backend API:", error);
        authStatus.textContent = "Error: Unable to connect to backend server."; // error message
    }
});

// Loads initiating public video
loadPublicStream();
renderTransmittedPhotos();