function performSearch() {
  const contentType = document.getElementById("content-type").value;
  const query = document.getElementById("search-query").value;

  fetch("/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type: contentType, query: query }),
  })
    .then((response) => response.json())
    .then((data) => displayResults(data, contentType))
    .catch((error) => console.error("Error:", error));
}


// function displayResults(results, contentType) {
//   const resultsDiv = document.getElementById("results");
//   resultsDiv.innerHTML = "";

//   results.forEach((item) => {
//     if (contentType === "Movies") {
//       const movieDiv = `<div>
//                 <h3>${item.title}</h3>
//                 <p>${item.overview}</p>
//                 ${
//                   item.poster
//                     ? `<img src="https://image.tmdb.org/t/p/w500${item.poster}" width="200">`
//                     : ""
//                 }
//             </div>`;
//       resultsDiv.innerHTML += movieDiv;
//     } else if (contentType === "Music") {
//       const musicDiv = `<div>
//                 <h3>${item.name} by ${item.artist}</h3>
//                 <a href="${item.url}" target="_blank">Listen on Spotify</a>
//             </div>`;
//       resultsDiv.innerHTML += musicDiv;
//     } else if (contentType === "Videos") {
//       const videoDiv = `<div>
//                 <h3>${item.title}</h3>
//                 <iframe width="560" height="315" src="https://www.youtube.com/embed/${item.video_id}" frameborder="0" allowfullscreen></iframe>
//             </div>`;
//       resultsDiv.innerHTML += videoDiv;
//     } else if (contentType === "Unsplash Images") {
//       const imageDiv = `<div>
//                 <img src="${item.url}" alt="${item.description}" width="200">
//                 <p>${item.description}</p>
//             </div>`;
//       resultsDiv.innerHTML += imageDiv;
//     }
//   });
// }


function displayResults(results, contentType) {
  const resultsDiv = document.getElementById("results");
  resultsDiv.innerHTML = ""; // Clear previous results

  if (results.length === 0) {
    resultsDiv.innerHTML = `<p class="no-results">No results found. Try a different search!</p>`;
    return;
  }

  results.forEach((item) => {
    let resultCard = "";

    if (contentType === "Movies") {
      resultCard = `
        <div class="result-card">
          ${
            item.poster
              ? `<img src="https://image.tmdb.org/t/p/w500${item.poster}" alt="${item.title} Poster" class="result-image">`
              : `<div class="no-image">🎥</div>`
          }
          <div class="result-info">
            <h3>${item.title}</h3>
            <p>${item.overview || "No description available."}</p>
          </div>
        </div>
      `;
    } else if (contentType === "Music") {
      resultCard = `
        <div class="result-card">
          <div class="no-image">🎵</div>
          <div class="result-info">
            <h3>${item.name}</h3>
            <p>By ${item.artist}</p>
            <a href="${item.url}" target="_blank" class="btn-link">Listen on Spotify</a>
          </div>
        </div>
      `;
    } else if (contentType === "Videos") {
      resultCard = `
        <div class="result-card">
          <iframe 
            width="100%" 
            height="200" 
            src="https://www.youtube.com/embed/${item.video_id}" 
            frameborder="0" 
            allowfullscreen>
          </iframe>
          <div class="result-info">
            <h3>${item.title}</h3>
          </div>
        </div>
      `;
    } else if (contentType === "Unsplash Images") {
      resultCard = `
        <div class="result-card">
          <img src="${item.url}" alt="${item.description}" class="result-image">
          <div class="result-info">
            <p>${item.description || "No description available."}</p>
          </div>
        </div>
      `;
    }

    resultsDiv.innerHTML += resultCard;
  });
}
