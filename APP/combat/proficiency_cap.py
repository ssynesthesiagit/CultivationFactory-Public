"""Proficiency Bonus ceiling for a Path level that has been reduced below its compiled level.

One formula shared by every Path that caps Proficiency Bonus (Body modes, Tribulation Vessel).
Callers keep their own 'only when reduced' guard and take min() with the actor's base bonus.
"""


def proficiency_cap(level):
    return 2+(max(1,int(level))-1)//4
