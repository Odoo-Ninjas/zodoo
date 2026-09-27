Der Watchdog laesst Container aus `compose run` jetzt in Ruhe.

`CRONJOB_RESTART_UNHEALTHY_CONTAINERS` hat bisher alle Container des Projekts
angefasst -- auch die, die `docker compose run` fuer einen einzelnen Job
anlegt. Solche Container gehoeren niemandem: bricht der Job ab (abgebrochener
Build, geschlossene Shell), bleiben sie ungesund liegen. Der Watchdog hat sie
daraufhin jede Minute neu gestartet, womit der Job jedes Mal von vorn begann.

Auf cicd-3dm hingen so fuenf verwaiste Container neun Tage lang an der
Maschine und hielten sie bei einer Last ueber 5, ohne dass ein einziger Build
lief. Erkannt werden sie am Label `com.docker.compose.oneoff`; gefiltert wird
nur auf den ausdruecklichen Wert `True`, damit eine Umgebung ohne dieses Label
sich weiter verhaelt wie bisher.
