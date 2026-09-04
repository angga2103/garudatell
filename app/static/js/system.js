async function loadStatus(){

    try{

        const r = await fetch("/admin/api/system/status");

        const status = await r.json();

        document.getElementById("cpu-value").innerText =
            status.cpu + "%";

        document.getElementById("ram-value").innerText =
            status.ram + "%";

        document.getElementById("disk-value").innerText =
            status.disk + "%";

        document.getElementById("uptime-value").innerText =
            status.uptime;

    }catch(e){

        console.log("STATUS ERROR",e);

    }

    try{

        const r = await fetch("/admin/api/system/services");

        const data = await r.json();

        Object.keys(data).forEach(function(name){

            let el=document.getElementById(
                "svc-"+name.replace(/ /g,"-").toLowerCase()
            );

            if(!el) return;

            el.innerHTML=
            '<span class="'+data[name].color+'">'+
            data[name].status+
            '</span>';

        });

    }catch(e){

        console.log("SERVICE ERROR",e);

    }

}

loadStatus();

setInterval(loadStatus,3000);
