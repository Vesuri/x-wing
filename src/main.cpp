#include "XWing.h"

int main(int argc, char** argv)
{
    XWing xwing;
    if (!xwing.isRunnable()) {
        return 20; // AmigaDOS FAIL
    }
    xwing.run();
    return 0;
}
