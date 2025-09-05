# free-filen-cloud-storage
I sure do love my daily does of breaking TOS of file hosting services, this it attempt two at this cause i was a dumbass the first time i tried it, cause i used drime where you would need to verify your email address everytime you logged in again, which is bad.

To run/install this thing do these command in the same directory as the requirments.txt and also the python file if you want

pip install uv

uv pip install -r requirements --system

playwright install

then just run the script, input whatever it asks you to input and then just run it, when trying to look at the browsers so turning headless of it does not put the browsers correctly but i cant be bothered to fix it, so go do it yourself or live with using it weird or just use it headless.

All the accounts will be saved in accounts.txt in the same directory, and then you can just go on filen.io login and upload and share files if you need to so badly. Each account is 20GB each i think, if you have files bigger than that you just split them up, google it, ask chatgpt or whatever on how to do it. Also i recommend using a VPN or proxy cause if you go above 5 threads it will rate limit you, which will i think and hope at least not make cloudflare think you are a bot

Also you need to use proxy_tester.py to validate the proxies, because most proxies do not accept POST Requests, and this script is mostly based on POST Request. It will sort out a lot of proxies, and some proxies might still not work, but most of them should. I recommend getting them using [KC-Scraper](https://github.com/Kuucheen/KC-Scraper) Because it gets you about 80000 proxies, that you will then have to test with https://github.com/openproxyspace/unfx-proxy-checker and only use the one it puts out to go throu the proxy_tester.py file, it will take a while for it to check throu all the proxies, but you will have to live with that. Also when its done deselect the transparent proxies in the menu and then export them with the format like this type://host:port, put those in proxies.txt, check them with the proxy_tester.py and then just put all the proxies from working_proxies.txt in proxies.txt.
