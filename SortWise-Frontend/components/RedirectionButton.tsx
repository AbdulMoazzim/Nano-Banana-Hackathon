"use client";
import { useRouter } from "next/navigation";
import { motion } from "motion/react";
import { Button } from "./ui/button";

export function RedirectionButton({text, link}: {text: string, link: string}) {
  const router = useRouter();
  return (
    <div className="text-center">
      <motion.div
        className="inline-block"
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.97 }}
      >
        <Button className="rounded-full px-4" onClick={() => router.push(link)}>
          {text}
        </Button>
      </motion.div>
    </div>
  );
}