
document.addEventListener("DOMContentLoaded", () => {

    document.querySelectorAll(".toggle-btn").forEach(btn => {

        btn.addEventListener("click", async () => {

            const pid = btn.dataset.id;

            btn.disabled = true;
            btn.innerText = "Loading...";

            try {
                const res = await fetch(`/admin/providers/${pid}/toggle`, {
                    method: "POST"
                });

                const data = await res.json();

                if (data.enabled) {
                    btn.innerText = "ON";
                    btn.classList.remove("btn-danger");
                    btn.classList.add("btn-success");
                } else {
                    btn.innerText = "OFF";
                    btn.classList.remove("btn-success");
                    btn.classList.add("btn-danger");
                }

            } catch (e) {
                alert("Toggle failed");
            }

            btn.disabled = false;
        });
    });

});
